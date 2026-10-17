"""Only the static export is publishable; application sources are never uploaded."""

import json
import sys
from unittest.mock import Mock

from scripts import infra


def test_deploy_uploads_only_built_web_assets(tmp_path, monkeypatch):
    web = tmp_path / "web"
    dist = web / "dist"
    (dist / "assets").mkdir(parents=True)
    (web / "package.json").write_text('{"private": true}')
    (web / "app.js").write_text("source-only")
    (dist / "index.html").write_text("static export")
    (dist / "assets" / "chat.js").write_text("bundled code")
    session = Mock()
    session.client.return_value.create_invalidation.return_value = {
        "Invalidation": {"Id": "fake-refresh"}
    }
    outputs = {
        key: {"value": value}
        for key, value in {
            "web_bucket": "fake-web",
            "distribution_id": "fake-distribution",
            "url": "https://example.invalid",
        }.items()
    }

    def terraform(directory, *args, **kwargs):
        if directory == "infra/bootstrap" and args[:2] == ("output", "-raw"):
            return "kloop-fake-tfstate"
        if args == ("output", "-json"):
            return json.dumps(outputs)

    monkeypatch.setattr(infra, "ROOT", tmp_path)
    monkeypatch.setattr(infra, "terraform", terraform)
    monkeypatch.setattr(infra.boto3, "Session", Mock(return_value=session))
    monkeypatch.setattr(sys, "argv", ["infra.py", "deploy"])
    for key in ("AWS_PROFILE", "AWS_DEFAULT_REGION", "TF_VAR_aws_profile", "TF_VAR_name_prefix"):
        monkeypatch.setenv(key, "fake")
    monkeypatch.setenv("NAME_PREFIX", "kloop")
    infra.main()
    uploads = session.client.return_value.upload_file.call_args_list
    assert {call.args[2] for call in uploads} == {"index.html", "assets/chat.js"}
    assert all(call.args[1] == "fake-web" for call in uploads)
    assert {call.kwargs["ExtraArgs"]["ContentType"] for call in uploads} == {
        "text/html",
        "text/javascript",
    }
