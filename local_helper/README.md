# Worktual Local Skills Helper

Run this helper on each user's machine when they open Worktual from the LAN server.

The helper listens only on:

```text
http://127.0.0.1:8799
```

It detects the current user's Home directory and installs skills into:

```text
/home/<user>/.worktual-skills
```

## Start

From the user machine, download and run the helper from the Worktual server:

```bash
WORKTUAL_SERVER="https://<worktual-server-host>:5174"
curl -kfsSL "$WORKTUAL_SERVER/api/local-helper/skills-helper.py" -o /tmp/worktual-skills-helper.py && python3 /tmp/worktual-skills-helper.py
```

If this repository is already available on the user machine:

```bash
./local_helper/start.sh
```

Or run Python directly:

```bash
python3 local_helper/skills_helper.py
```

## Verify

```bash
curl http://127.0.0.1:8799/health
```

Expected response includes:

```json
{
  "ok": true,
  "service": "worktual-skills-helper",
  "skills_dir": "/home/<user>/.worktual-skills"
}
```

## Use From Worktual

1. Start the helper in the user's/customer's own terminal, not only on the Worktual server.
2. Open the LAN Worktual app, for example `https://<worktual-server-host>:5174`.
3. Click **Check Local Helper** in the new project dialog to confirm that this browser can reach `http://127.0.0.1:8799/health` on the same user machine.
4. Import or reconnect a local project.
5. Confirm `/home/<user>/.worktual-skills/skills.md` exists.

The helper never binds to the LAN. It is reachable only from the browser on the same user machine.

## Terminal Actions

The helper also exposes a small terminal workflow API for local testing before commits.

List allowed actions:

```bash
curl http://127.0.0.1:8799/actions
```

Run a safe predefined action:

```bash
curl -X POST http://127.0.0.1:8799/run-action \
  -H "Content-Type: application/json" \
  --data '{"action":"git_status","workspace":"/home/kathir/Documents/my-project"}'
```

Supported predefined actions:

- `git_status`
- `git_diff`
- `python_tests`
- `frontend_build`
- `npm_test`
- `frontend_install`
- `frontend_install_and_build`
- `python_install_requirements`
- `python_install_and_test`

## One-click install from Worktual UI

In the app, click **Install on this computer**:

- If this helper is already running, Worktual calls `frontend_install_and_build` on your linked project folder immediately.
- If the helper is offline, Worktual downloads `worktual-local-setup.sh`. Run it once in your terminal:

```bash
bash ~/Downloads/worktual-local-setup.sh /home/you/your-project
```

That script starts the helper and runs `npm install` + `npm run build` when a project path is provided.

Download directly:

```bash
curl -kfsSL "$WORKTUAL_SERVER/api/local-helper/bootstrap.sh" -o ~/Downloads/worktual-local-setup.sh
```

When a frontend dependency error appears, run the install-and-retry workflow in the user's local project folder:

```bash
curl -X POST http://127.0.0.1:8799/run-action \
  -H "Content-Type: application/json" \
  --data '{"action":"frontend_install_and_build","workspace":"/home/<user>/Documents/my-project"}'
```

The frontend install action runs `npm install --ignore-scripts` before retrying `npm run build`.

For Python projects with `requirements.txt`, use:

```bash
curl -X POST http://127.0.0.1:8799/run-action \
  -H "Content-Type: application/json" \
  --data '{"action":"python_install_and_test","workspace":"/home/<user>/Documents/my-project"}'
```

The workspace must be inside the current user's Home directory unless extra roots are configured:

```bash
WORKTUAL_HELPER_ALLOWED_ROOTS="/mnt/work:/opt/projects" python3 /tmp/worktual-skills-helper.py
```

Custom commands are disabled by default. Enable them only on trusted machines:

```bash
WORKTUAL_HELPER_ALLOW_CUSTOM_COMMANDS=1 python3 /tmp/worktual-skills-helper.py
```

Then run:

```bash
curl -X POST http://127.0.0.1:8799/run-action \
  -H "Content-Type: application/json" \
  --data '{"action":"custom","command":"npm run lint","workspace":"/home/kathir/Documents/my-project"}'
```

Keep the helper bound to `127.0.0.1`; do not expose it on the LAN.
