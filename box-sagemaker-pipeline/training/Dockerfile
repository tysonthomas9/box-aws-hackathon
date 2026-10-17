# AWS Deep Learning Container (PyTorch 2.x + CUDA) as the base.
# Region in the registry host must match where you run training.
FROM 763104351884.dkr.ecr.us-west-2.amazonaws.com/pytorch-training:2.4.0-gpu-py311-cu124-ubuntu22.04-sagemaker

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY train_qlora.py /opt/ml/code/train_qlora.py

# SageMaker runs `train` by default; point it at our script.
ENTRYPOINT ["python", "/opt/ml/code/train_qlora.py"]
