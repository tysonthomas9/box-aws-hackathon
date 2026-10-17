"""HTTP surface; all operations are injected and no clients are made at import."""

import hmac
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Literal

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from kloop.schemas import ExtractionRow, PinnedModel, Schema
from kloop.web.security import COOKIE, Security, epoch


class Login(Schema):
    password: str = Field(min_length=1, max_length=1024, repr=False)


class VersionChoice(Schema):
    version_id: str | None = Field(default=None, min_length=1, max_length=200)


class Ask(VersionChoice):
    question: str = Field(min_length=1, max_length=2000)


class Decision(Schema):
    action: Literal["approve", "edit", "reject"]
    edited: ExtractionRow | None = None


class Train(Schema):
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,100}$")


class Mode(Schema):
    mode: Literal["off", "exceptions", "all"]


@dataclass
class Services:
    extraction: object
    jobs: object
    select_models: object  # () -> {without/with/search: {arn, version_id, snapshot_sha256}}
    sources: object
    ingress: object
    training: object
    results: object
    training_busy: type[Exception] = ValueError
    training_control: object = None
    version_loading: object = None
    model_guard: object = nullcontext
    version_catalog: object = None


def create_app(services: Services, security: Security, throttle, *, clock=epoch) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        def deny(code, message):
            return JSONResponse(
                {"detail": message}, status_code=code, headers={"Cache-Control": "no-store"}
            )

        if not hmac.compare_digest(
            request.headers.get("x-kloop-origin", "").encode(), security.origin_key.encode()
        ):
            return deny(403, "Use the application URL")
        path, method = request.url.path, request.method
        webhook = path == "/api/box-webhook" and method == "POST"
        login = path == "/api/login" and method == "POST"
        event = request.scope.get("aws.event", {})
        ip = event.get("requestContext", {}).get("http", {}).get("sourceIp")
        ip = ip or (request.client.host if request.client else "unknown")
        # Trust API Gateway's source IP, never a caller-supplied forwarding header.
        if not webhook and not throttle.allow(
            f"{'login' if login else 'api'}:{ip}", 10 if login else 120, clock()
        ):
            return deny(429, "Too many requests; try again in a minute")
        csrf = security.verify(request.cookies.get(COOKIE, ""), clock())
        if not (login or webhook) and csrf is None:
            return deny(401, "Sign in to continue")
        if method not in {"GET", "HEAD", "OPTIONS"} and not webhook:
            if request.headers.get("origin") != security.public_origin:
                return deny(403, "Request origin does not match the application")
            if not login and not hmac.compare_digest(
                request.headers.get("x-csrf-token", "").encode(), (csrf or "").encode()
            ):
                return deny(403, "Refresh the page and try again")
        if method == "POST" and path in {"/api/ask", "/api/warm-up"}:
            if not throttle.allow(f"jobs:{ip}", 6, clock()):
                return deny(429, "Too many comparisons; try again in a minute")
        request.state.csrf = csrf
        try:
            response = await call_next(request)
        except Exception:
            return deny(503, "Service unavailable; try again")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # FastAPI's default error includes input values, including passwords.
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Record not found"}, status_code=404)

    @app.exception_handler(ValueError)
    async def conflict(request, exc):
        return JSONResponse({"detail": "Request conflicts with current state"}, status_code=409)

    @app.post("/api/login")
    def login(body: Login, response: Response):
        if not hmac.compare_digest(body.password.encode(), security.password.encode()):
            return JSONResponse({"detail": "Incorrect password"}, status_code=401)
        token, csrf = security.issue(clock())
        response.set_cookie(
            COOKIE,
            token,
            max_age=security.lifetime,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return {"csrf_token": csrf}

    @app.get("/api/session")
    def session(request: Request):
        return {"csrf_token": request.state.csrf}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")
        return {"signed_out": True}

    @app.post("/api/box-webhook")
    async def webhook(request: Request):
        raw = await request.body()
        if len(raw) > 256_000:
            return JSONResponse({"detail": "Event too large"}, status_code=413)
        import base64

        result = services.ingress.webhook(
            {
                "body": base64.b64encode(raw).decode(),
                "isBase64Encoded": True,
                "headers": dict(request.headers),
            }
        )
        return Response(content=result["body"], status_code=result["statusCode"])

    @app.get("/api/sources")
    def sources():
        return services.sources()

    @app.post("/api/sync")
    def sync():
        services.ingress.sync_now()
        return JSONResponse({"status": "queued"}, status_code=202)

    @app.get("/api/reviews")
    def reviews():
        snapshot = services.extraction.snapshot()
        effective = {i.id: i.model_dump(mode="json") for i in snapshot.items}
        return {
            "mode": services.extraction.get_review_mode(),
            "snapshot_sha256": snapshot.sha256,
            "reviews": [
                {**r.model_dump(mode="json"), "previous": effective.get(r.item_id)}
                for r in services.extraction.reviews()
            ],
        }

    @app.post("/api/reviews/{id}")
    def decide(id: str, body: Decision):
        return services.extraction.decide(
            id, body.action, actor="shared-password reviewer", edited=body.edited
        )

    @app.post("/api/review-mode")
    def review_mode(body: Mode):
        services.extraction.set_review_mode(body.mode)
        return {"mode": services.extraction.get_review_mode()}

    @app.get("/api/serving")
    def serving():
        selected = services.select_models()
        snapshot = services.extraction.snapshot()
        trained = selected.get("with")
        return {
            "models": selected,
            "approved_snapshot_sha256": snapshot.sha256,
            "stale": bool(trained and trained["snapshot_sha256"] != snapshot.sha256),
        }

    def enqueue(question, warm_up=False, version_id=None):
        with services.model_guard():
            return enqueue_guarded(question, warm_up, version_id)

    def enqueue_guarded(question, warm_up=False, version_id=None):
        if not question.strip():
            return JSONResponse({"detail": "Enter a question"}, status_code=422)
        # Read the pointer ONCE for the whole comparison, then pin every mode.
        selected = dict(services.select_models())
        if version_id is not None:
            if services.version_catalog is None:
                raise ValueError("Version selection is unavailable")
            selected["with"] = services.version_catalog.resolve(version_id)
        snapshot = services.extraction.snapshot()
        rows = []
        unavailable = []
        errors = {}
        if warm_up:
            pins = [
                PinnedModel(
                    model_arn=selected[mode]["arn"], model_version_id=selected[mode]["version_id"]
                )
                for mode in ("without", "with")
                if selected.get(mode) is not None
            ]
            if not pins:
                return JSONResponse({"detail": "No models are available"}, status_code=409)
            job = services.jobs.create(
                question,
                "without",
                pins[0].model_arn,
                pins[0].model_version_id,
                snapshot.sha256,
                warm_up=True,
                warm_up_models=pins,
            )
            return JSONResponse(
                {
                    "jobs": [job.model_dump(mode="json")],
                    "unavailable": [m for m in ("without", "with") if selected.get(m) is None],
                },
                status_code=202,
            )
        for mode in ("without", "with", "search"):
            model = selected.get(mode)
            if model is None:
                unavailable.append(mode)
                continue
            try:
                job = services.jobs.create(
                    question,
                    mode,
                    model["arn"],
                    model["version_id"],
                    snapshot.sha256,
                )
            except RuntimeError:
                errors[mode] = "Queue unavailable; submit again"
                continue
            rows.append(job.model_dump(mode="json"))
        return JSONResponse(
            {"jobs": rows, "unavailable": unavailable, "errors": errors},
            status_code=202 if rows else 503,
        )

    @app.post("/api/ask")
    def ask(body: Ask):
        return enqueue(body.question, version_id=body.version_id)

    @app.post("/api/warm-up")
    def warm_up(body: VersionChoice | None = None):
        return enqueue("Reply with READY.", True, body.version_id if body else None)

    @app.get("/api/versions")
    def versions():
        return services.version_catalog.list()

    @app.get("/api/versions/{id}/training-rows")
    def training_rows(
        id: str,
        kind: Literal["fact", "procedure", "unknown", "near_miss", "replay"] | None = None,
        q: str = Query(default="", max_length=200),
        page: int = Query(default=1, ge=1),
    ):
        return services.version_catalog.training_rows(id, kind=kind, q=q, page=page)

    @app.get("/api/jobs/{id}")
    def poll(id: str):
        job = services.jobs.get(id)
        if job is None:
            raise KeyError(id)
        return job

    @app.post("/api/train")
    def train(body: Train):
        try:
            return services.training.start(body.request_id, clock())
        except services.training_busy:
            return JSONResponse({"detail": "Training is already active"}, status_code=409)

    @app.get("/api/training")
    def training():
        versions = services.training.versions()
        control = (
            services.training_control(versions, clock()) if services.training_control else None
        )
        return {"versions": versions, "control": control}

    @app.get("/api/training/{id}")
    def progress(id: str):
        result = services.training.status(id)
        if result is None:
            raise KeyError(id)
        return result

    @app.post("/api/versions/{id}/load")
    def load_version(id: str):
        if services.version_loading is None:
            raise ValueError("Version loading is not configured")
        try:
            return JSONResponse(services.version_loading.load(id), status_code=202)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        except services.training_busy:
            return JSONResponse(
                {"detail": "Training or loading is already active"}, status_code=409
            )

    @app.post("/api/versions/{id}/unload")
    def unload_version(id: str):
        if services.version_loading is None:
            raise ValueError("Version loading is not configured")
        try:
            return services.version_loading.unload(id)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        except services.training_busy:
            return JSONResponse(
                {"detail": "Training or loading is already active"}, status_code=409
            )

    @app.get("/api/results")
    def results():
        # An allowlist keeps private sealed answers and questions out of this surface.
        allowed = {
            "id",
            "model_version_id",
            "split",
            "question_set_sha256",
            "scores",
            "counts",
            "diagnostics",
            "medical_counts",
            "bindings",
            "caveats",
            "gate",
            "paired",
            "overlap_audit",
        }
        return {
            "reports": [{k: v for k, v in r.items() if k in allowed} for r in services.results()],
            "versions": services.training.versions(),
        }

    return app
