# Repository agent skills

This repository vendors 29 skills: the 24 installed by AWS Agent Toolkit and five from [box/skills](https://github.com/box/skills). Claude Code discovers `.claude/skills/`; Codex and agents that support the universal location discover the same files through `.agents/skills -> ../.claude/skills`. No global installation or credentials are needed to discover the skills. Tools used by individual skills may still require separate installation and authentication. Newly added skills become available on the next agent turn/session, depending on the client.

## Sources and versions

AWS skills were copied without edits from the AWS Agent Toolkit installation on 2026-10-17 using AWS CLI 2.38.1. `aws agent-toolkit list-installed-skills --agent claude-code` supplied the exact inventory. The Toolkit `add-skill` help supports only global agent targets, so the installed folders were copied with their `.aws-skill-metadata` versions retained. The installed AWS bundles contained no LICENSE or NOTICE files; none were removed and no license is inferred here.

Box skills were installed in a temporary project using `npx skills add <pinned-local-clone> --skill box box-cli box-mcp box-sdk-development box-integration-best-practices --agent claude-code --copy --yes`, then copied here. Source: [box/skills at 84320fd8984b95cab430335cd341d8314c14bbcb](https://github.com/box/skills/tree/84320fd8984b95cab430335cd341d8314c14bbcb). Its repository MIT license is preserved in `BOX-LICENSE`. Legal workflow skills and MCP configuration are excluded.

`sources.json` records each source/version and a content fingerprint. For each skill, the tree SHA-256 hashes sorted file paths relative to its directory, each followed by a NUL, its file bytes, and another NUL. It excludes this README, the manifest, and the shared Box license.

| Skill | Source | Version or commit |
| --- | --- | --- |
| `amazon-bedrock` | AWS Agent Toolkit | `v7` |
| `aws-ai-ml` | AWS Agent Toolkit | `v6` |
| `aws-auth` | AWS Agent Toolkit | `v1` |
| `aws-billing-and-cost-management` | AWS Agent Toolkit | `v1` |
| `aws-blocks` | AWS Agent Toolkit | `v2` |
| `aws-cdk` | AWS Agent Toolkit | `v2` |
| `aws-cloudformation` | AWS Agent Toolkit | `v3` |
| `aws-compute` | AWS Agent Toolkit | `v2` |
| `aws-containers` | AWS Agent Toolkit | `v4` |
| `aws-database` | AWS Agent Toolkit | `v3` |
| `aws-deployment` | AWS Agent Toolkit | `v1` |
| `aws-iam` | AWS Agent Toolkit | `v3` |
| `aws-messaging-and-streaming` | AWS Agent Toolkit | `v4` |
| `aws-networking` | AWS Agent Toolkit | `v2` |
| `aws-observability` | AWS Agent Toolkit | `v8` |
| `aws-sdk-js-v3-usage` | AWS Agent Toolkit | `v1` |
| `aws-sdk-python-usage` | AWS Agent Toolkit | `v1` |
| `aws-sdk-swift-usage` | AWS Agent Toolkit | `v1` |
| `aws-security` | AWS Agent Toolkit | `v1` |
| `aws-serverless` | AWS Agent Toolkit | `v5` |
| `aws-storage` | AWS Agent Toolkit | `v1` |
| `aws-well-architected-review` | AWS Agent Toolkit | `v2` |
| `box` | box/skills | `84320fd8984b95cab430335cd341d8314c14bbcb` |
| `box-cli` | box/skills | `84320fd8984b95cab430335cd341d8314c14bbcb` |
| `box-integration-best-practices` | box/skills | `84320fd8984b95cab430335cd341d8314c14bbcb` |
| `box-mcp` | box/skills | `84320fd8984b95cab430335cd341d8314c14bbcb` |
| `box-sdk-development` | box/skills | `84320fd8984b95cab430335cd341d8314c14bbcb` |
| `launch-with-aws` | AWS Agent Toolkit | `v5` |
| `signing-in-to-aws` | AWS Agent Toolkit | `v1` |

## Updating

1. AWS: use the Toolkit's read-only `list-installed-skills --agent claude-code` and `check-skill-updates` commands to inspect versions. For a repo-only refresh, use `get-skill-metadata` and `get-skill-file` at explicit versions, or copy a separately maintained installation of these same 24 folders. Do not run global `add-skill` or `update-skill` as part of a repo-only update. Retain all files, version metadata, and any licenses shipped with updated bundles.
2. Box: clone `box/skills` into a temporary directory with `gh repo clone box/skills`, choose and record a reviewed full commit SHA, and check it out detached. Run the five-skill installation command above from a temporary project; copy only those installed skill folders into `.claude/skills/`, together with the upstream license. Using a temporary project avoids the installer's duplicate universal/Claude copies in this repo. Do not copy its MCP configuration or legal workflows.
3. Refresh this table and `sources.json` (including tree fingerprints), check each SKILL.md frontmatter for nonempty `name` and `description`, and review the diff for secrets or unrelated files. Keep `.agents/skills` as a relative symlink; do not duplicate the skill trees.
4. Verify `find .claude/skills -name SKILL.md | wc -l` returns 29, `readlink .agents/skills` returns `../.claude/skills`, and `git diff --check` passes. Restart clients if they cache skill discovery.
