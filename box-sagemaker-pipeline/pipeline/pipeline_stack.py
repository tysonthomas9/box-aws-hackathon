"""Infrastructure for the scheduled Box -> S3 -> SageMaker QLoRA retraining pipeline.

Flow:
    EventBridge Scheduler
        -> Step Functions state machine
            1. PrepareDataset Lambda (DDB -> Box -> S3 JSONL, marks rows trained)
            2. Choice: enough new data?  no -> succeed (skip run)
            3. SageMaker CreateTrainingJob (.sync) - QLoRA on Qwen + adapter merge
            4. (future) Evaluate -> Gate -> Deploy
"""
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Size,
    Stack,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_scheduler as scheduler,
    aws_secretsmanager as secretsmanager,
    aws_ssm as ssm,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
import json
from constructs import Construct

STATUS_INDEX = "status-index"
MODEL_NAME_PREFIX = "pharma-qwen-"
CODE_PREFIX = "code/training/"
CODE_CHANNEL_DIR = "/opt/ml/input/data/code"
# AWS Deep Learning Container (PyTorch 2.3, CUDA 12.1). The SageMaker training toolkit
# in this image copies the "code" channel to /opt/ml/code, pip-installs its
# requirements.txt, then runs train_qlora.py - so no custom Docker image is needed.
DEFAULT_TRAINING_IMAGE = (
    "763104351884.dkr.ecr.{region}.amazonaws.com/pytorch-training:2.3.0-gpu-py311-cu121-ubuntu20.04-sagemaker"
)


class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        schedule_expression: str,
        training_image_uri: str,
        box_secret_name: str,
        box_metadata_template: str,
        min_new_examples: int,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------
        # S3: dataset snapshots + trained model artifacts. Private, TLS-only.
        # ------------------------------------------------------------------
        bucket = s3.Bucket(
            self,
            "PipelineBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ------------------------------------------------------------------
        # DynamoDB: one row per validated Box file.
        #   file_id (PK) | status (validated|trained) | validated_at | trained_in
        # Written by the Box webhook -> SQS -> Lambda path (separate component).
        # ------------------------------------------------------------------
        table = dynamodb.Table(
            self,
            "ValidatedFilesTable",
            partition_key=dynamodb.Attribute(name="file_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        table.add_global_secondary_index(
            index_name=STATUS_INDEX,
            partition_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="validated_at", type=dynamodb.AttributeType.STRING),
        )

        box_secret = secretsmanager.Secret.from_secret_name_v2(self, "BoxSecret", box_secret_name)

        # ------------------------------------------------------------------
        # Lambda: PrepareDataset (Option A - DDB read + Box fetch + S3 write).
        # Standard library + boto3 only, so no bundling step is needed.
        # ------------------------------------------------------------------
        prepare_fn = lambda_.Function(
            self,
            "PrepareDatasetFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambdas/prepare_dataset"),
            timeout=Duration.minutes(15),
            memory_size=1024,
            log_retention=logs.RetentionDays.ONE_MONTH,
            environment={
                "TABLE_NAME": table.table_name,
                "STATUS_INDEX": STATUS_INDEX,
                "BUCKET_NAME": bucket.bucket_name,
                "BOX_SECRET_NAME": box_secret_name,
                "BOX_METADATA_TEMPLATE": box_metadata_template,
                "MIN_NEW_EXAMPLES": str(min_new_examples),
            },
        )
        table.grant_read_write_data(prepare_fn)
        bucket.grant_read_write(prepare_fn, "datasets/*")
        box_secret.grant_read(prepare_fn)

        # ------------------------------------------------------------------
        # SageMaker training execution role - scoped to what the job needs.
        # ------------------------------------------------------------------
        sm_role = iam.Role(
            self,
            "SageMakerTrainingRole",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
        )
        bucket.grant_read(sm_role, "datasets/*")
        bucket.grant_read(sm_role, f"{CODE_PREFIX}*")
        bucket.grant_read_write(sm_role, "models/*")

        # Upload the training script + requirements to S3 as the "code" channel.
        s3deploy.BucketDeployment(
            self,
            "TrainingCode",
            sources=[s3deploy.Source.asset("training", exclude=["Dockerfile", "__pycache__"])],
            destination_bucket=bucket,
            destination_key_prefix=CODE_PREFIX,
            prune=True,
        )
        if not training_image_uri:
            training_image_uri = DEFAULT_TRAINING_IMAGE.format(region=self.region)
        sm_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                ],
                resources=["*"],
            )
        )
        sm_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                    "cloudwatch:PutMetricData",
                ],
                resources=["*"],
            )
        )

        # ------------------------------------------------------------------
        # Step Functions states
        # ------------------------------------------------------------------
        prepare_task = tasks.LambdaInvoke(
            self,
            "PrepareDataset",
            lambda_function=prepare_fn,
            payload_response_only=True,
            result_path="$.dataset",
            retry_on_service_exceptions=True,
        )

        skip_run = sfn.Succeed(self, "SkipRun_NotEnoughNewData")

        train_task = tasks.SageMakerCreateTrainingJob(
            self,
            "QLoRATrainingJob",
            integration_pattern=sfn.IntegrationPattern.RUN_JOB,  # .sync - waits for completion
            training_job_name=sfn.JsonPath.string_at("$.dataset.job_name"),
            role=sm_role,
            algorithm_specification=tasks.AlgorithmSpecification(
                training_image=tasks.DockerImage.from_registry(training_image_uri),
                training_input_mode=tasks.InputMode.FILE,
            ),
            input_data_config=[
                tasks.Channel(
                    channel_name="training",
                    data_source=tasks.DataSource(
                        s3_data_source=tasks.S3DataSource(
                            s3_location=tasks.S3Location.from_json_expression("$.dataset.train_s3_uri"),
                            s3_data_type=tasks.S3DataType.S3_PREFIX,
                        )
                    ),
                ),
                tasks.Channel(
                    channel_name="code",
                    data_source=tasks.DataSource(
                        s3_data_source=tasks.S3DataSource(
                            s3_location=tasks.S3Location.from_bucket(bucket, CODE_PREFIX),
                            s3_data_type=tasks.S3DataType.S3_PREFIX,
                        )
                    ),
                ),
            ],
            output_data_config=tasks.OutputDataConfig(
                s3_output_location=tasks.S3Location.from_json_expression("$.dataset.output_s3_uri"),
            ),
            resource_config=tasks.ResourceConfig(
                instance_count=1,
                # CDK prefixes "ml." -> ml.g5.2xlarge (1x A10G, 24 GB) fits 7B QLoRA.
                instance_type=ec2.InstanceType("g5.2xlarge"),
                volume_size=Size.gibibytes(200),
            ),
            stopping_condition=tasks.StoppingCondition(max_runtime=Duration.hours(8)),
            hyperparameters={
                # Script-mode settings read by the SageMaker training toolkit (JSON-encoded).
                "sagemaker_program": '"train_qlora.py"',
                "sagemaker_submit_directory": f'"{CODE_CHANNEL_DIR}"',
                "base_model": "Qwen/Qwen2.5-7B-Instruct",
                "epochs": "3",
                "learning_rate": "0.0002",
                # Larger adapter so it can hold document facts, not just output style.
                "lora_r": "64",
                "lora_alpha": "128",
                # Chunks are ~1.5k tokens; 2048 bounds memory/time on a single A10G.
                "max_seq_len": "2048",
                # Training script uploads the merged HF weights here for Bedrock import.
                "export_s3_uri": sfn.JsonPath.string_at("$.dataset.export_s3_uri"),
            },
            result_path="$.training",
        )

        training_failed = sfn.Fail(self, "TrainingFailed", cause="SageMaker training job failed")
        train_task.add_catch(training_failed, result_path="$.error")

        # ------------------------------------------------------------------
        # Deploy: Bedrock Custom Model Import -> wait -> register as live
        # ------------------------------------------------------------------
        import_role = iam.Role(
            self,
            "BedrockImportRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock:{self.region}:{self.account}:model-import-job/*"},
                },
            ),
        )
        bucket.grant_read(import_role, "models/*")

        live_param = ssm.StringParameter(
            self,
            "LiveModelParam",
            parameter_name="/box-sagemaker-pipeline/live-model",
            string_value=json.dumps({"model_arn": None, "note": "set by the pipeline after a successful deploy"}),
            description="Currently deployed (live) Bedrock imported model for the pharma pipeline",
        )

        deploy_fn = lambda_.Function(
            self,
            "DeployModelFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambdas/deploy_model"),
            timeout=Duration.minutes(2),
            log_retention=logs.RetentionDays.ONE_MONTH,
            environment={
                "IMPORT_ROLE_ARN": import_role.role_arn,
                "LIVE_MODEL_PARAM": live_param.parameter_name,
                "MODEL_NAME_PREFIX": MODEL_NAME_PREFIX,
                "KEEP_MODELS": "2",
            },
        )
        live_param.grant_write(deploy_fn)
        import_role.grant_pass_role(deploy_fn)
        deploy_fn.add_to_role_policy(
            iam.PolicyStatement(
                # CreateModelImportJob is authorized against "*" (the job has no ARN until created).
                actions=["bedrock:CreateModelImportJob"],
                resources=["*"],
            )
        )
        deploy_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:GetModelImportJob", "bedrock:TagResource"],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:model-import-job/*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:imported-model/*",
                ],
            )
        )
        deploy_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:ListImportedModels"],
                resources=["*"],  # list APIs don't support resource-level scoping
            )
        )
        deploy_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:DeleteImportedModel"],
                resources=[f"arn:aws:bedrock:{self.region}:{self.account}:imported-model/*"],
            )
        )

        start_import = tasks.LambdaInvoke(
            self,
            "StartBedrockImport",
            lambda_function=deploy_fn,
            payload=sfn.TaskInput.from_object(
                {
                    "action": "start",
                    "import_job_name": sfn.JsonPath.string_at("$.dataset.import_job_name"),
                    "imported_model_name": sfn.JsonPath.string_at("$.dataset.imported_model_name"),
                    "weights_s3_uri": sfn.JsonPath.string_at("$.dataset.export_s3_uri"),
                }
            ),
            payload_response_only=True,
            result_path="$.deploy",
            retry_on_service_exceptions=True,
        )

        wait_import = sfn.Wait(self, "WaitForImport", time=sfn.WaitTime.duration(Duration.minutes(2)))

        check_import = tasks.LambdaInvoke(
            self,
            "CheckImportStatus",
            lambda_function=deploy_fn,
            payload=sfn.TaskInput.from_object(
                {"action": "status", "job_arn": sfn.JsonPath.string_at("$.deploy.job_arn")}
            ),
            payload_response_only=True,
            result_path="$.deploy",
            retry_on_service_exceptions=True,
        )

        register_model = tasks.LambdaInvoke(
            self,
            "RegisterLiveModel",
            lambda_function=deploy_fn,
            payload=sfn.TaskInput.from_object(
                {
                    "action": "register",
                    "model_arn": sfn.JsonPath.string_at("$.deploy.model_arn"),
                    "model_name": sfn.JsonPath.string_at("$.deploy.model_name"),
                    "run_id": sfn.JsonPath.string_at("$.dataset.run_id"),
                    "training_job": sfn.JsonPath.string_at("$.dataset.job_name"),
                    "weights_s3_uri": sfn.JsonPath.string_at("$.dataset.export_s3_uri"),
                }
            ),
            payload_response_only=True,
            result_path="$.registry",
            retry_on_service_exceptions=True,
        )

        deploy_failed = sfn.Fail(
            self, "DeployFailed", cause="Bedrock Custom Model Import failed",
            error="BedrockImportFailed",
        )
        deployed = sfn.Succeed(self, "ModelDeployed")

        # No Catch on the deploy tasks: an error fails the task itself, so the execution
        # can be redriven from that exact step (e.g. after an IAM fix) without retraining.

        import_done = (
            sfn.Choice(self, "ImportComplete?")
            .when(sfn.Condition.string_equals("$.deploy.status", "Completed"), register_model.next(deployed))
            .when(sfn.Condition.string_equals("$.deploy.status", "Failed"), deploy_failed)
            .otherwise(wait_import)
        )
        wait_import.next(check_import).next(import_done)

        deploy_chain = start_import.next(wait_import)

        definition = prepare_task.next(
            sfn.Choice(self, "EnoughNewData?")
            .when(sfn.Condition.boolean_equals("$.dataset.enough_data", False), skip_run)
            .otherwise(train_task.next(deploy_chain))
        )

        state_machine = sfn.StateMachine(
            self,
            "RetrainStateMachine",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(12),
            tracing_enabled=True,
        )
        # The .sync CreateTrainingJob integration tags the job; CDK doesn't grant this by default.
        state_machine.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sagemaker:AddTags"],
                resources=[f"arn:aws:sagemaker:{self.region}:{self.account}:training-job/*"],
            )
        )

        # ------------------------------------------------------------------
        # EventBridge Scheduler -> Step Functions
        # ------------------------------------------------------------------
        scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        state_machine.grant_start_execution(scheduler_role)

        scheduler.CfnSchedule(
            self,
            "RetrainSchedule",
            schedule_expression=schedule_expression,
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=state_machine.state_machine_arn,
                role_arn=scheduler_role.role_arn,
                input="{}",
            ),
        )
