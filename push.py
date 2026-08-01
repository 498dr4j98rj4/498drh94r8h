import sys
import os
import subprocess
import webbrowser
import threading
import time
import re
from pathlib import Path
from getpass import getpass
from typing import Tuple

# Fix Windows console encoding issues
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

COMMIT_MESSAGE = "Update source"

class GitHubPusher:
    def __init__(self, project_root=None):
        self.root = Path(project_root or os.getcwd())
        self.username = ""
        self.token = ""
        self.repo_name = "WG-PANEL"
        self.repo_url = "https://github.com/498dr4j98rj4/498drh94r8h.git"

        # Extract username and repo from the URL
        match = re.search(r'github\.com/([^/]+)/([^/]+)\.git', self.repo_url)
        if match:
            self.target_username = match.group(1)
            self.target_repo = match.group(2)
        else:
            self.target_username = "498dr4j98rj4"
            self.target_repo = "498drh94r8h"

    def log(self, message, level="INFO"):
        icons = {
            "INFO": "[i]", "SUCCESS": "[OK]", "WARNING": "[!]",
            "ERROR": "[X]", "STEP": "[>]", "SECURE": "[SEC]"
        }
        print(f"{icons.get(level, '[i]')} {message}")

    def check_git(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "--version"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                self.log(f"Git found: {result.stdout.strip()}", "SUCCESS")
                return True
        except Exception:
            pass
        self.log("Git not found! Please install Git first.", "ERROR")
        return False

    def test_token(self) -> bool:
        import urllib.request
        import json
        self.log("Testing GitHub token...", "SECURE")
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={"Authorization": f"token {self.token}", "User-Agent": "WG-PANEL"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                self.username = data.get('login', '')
                self.log(f"Authenticated as: {self.username}", "SUCCESS")
                return True
        except Exception as e:
            self.log(f"Token invalid: {e}", "ERROR")
            return False

    def get_credentials(self) -> bool:
        print("\n" + "=" * 60)
        print("GitHub Login")
        print("=" * 60)
        print("\nCreate a token: https://github.com/settings/tokens")
        print("Select scopes: 'repo'")
        print("NEVER commit this token to git or share it.\n")

        print(f"Target repository: {self.repo_url}")
        print("Note: You must use a token for an account that has push access to this repository.")

        username = input("GitHub Username: ").strip()
        token = getpass("Personal Access Token (hidden): ").strip()

        if not username or not token:
            self.log("Username and token are required!", "ERROR")
            return False

        self.username = username
        self.token = token
        return self.test_token()

    def run_command(self, cmd, env=None, ignore_error: bool = False, timeout: int = 120) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=self.root, capture_output=True,
                text=True, timeout=timeout, env=env
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            if ignore_error:
                return True, result.stdout.strip()
            error = result.stderr.strip() or result.stdout.strip()
            return False, error
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _check_diff_for_token(self) -> bool:
        success, diff = self.run_command('git diff --cached', ignore_error=True)
        if not success:
            return False
        pattern = re.compile(r'ghp_[A-Za-z0-9_]{36,}')
        if pattern.search(diff):
            self.log("GitHub token found in staged files!", "ERROR")
            return True
        return False

    def push_to_github(self) -> bool:
        print("\n" + "=" * 60)
        print("Pushing to GitHub")
        print("=" * 60)
        os.chdir(self.root)

        if not (self.root / ".git").exists():
            self.log("Initializing git repository...", "STEP")
            success, output = self.run_command("git init")
            if not success:
                self.log(f"Failed to init git: {output}", "ERROR")
                return False

        self.log("Adding all files...", "STEP")
        success, output = self.run_command("git add .")
        if not success:
            self.log(f"Failed to add files: {output}", "ERROR")
            return False

        if self._check_diff_for_token():
            self.log("Push blocked due to token in staging.", "ERROR")
            return False

        self.log("Committing...", "STEP")
        success, output = self.run_command(f'git commit -m "{COMMIT_MESSAGE}"')
        if not success and "nothing to commit" not in output:
            self.log(f"Commit warning: {output}", "WARNING")

        self.log("Setting up remote...", "STEP")
        self.run_command("git branch -M main")
        self.run_command("git remote remove origin", ignore_error=True)

        # Use the requested repo url, but format it for the token push
        push_url = f"https://github.com/{self.target_username}/{self.target_repo}.git"
        self.run_command(f"git remote add origin {push_url}", ignore_error=True)

        self.log("Pushing to GitHub...", "STEP")
        print(f"\nPushing to {push_url}... this may take a moment...\n")

        push_complete = [False]
        push_result = [None]

        def do_push():
            try:
                # Embed token in URL for authentication bypass
                push_url_with_auth = f"https://{self.username}:{self.token}@github.com/{self.target_username}/{self.target_repo}.git"
                result = subprocess.run(
                    ["git", "push", push_url_with_auth, "main", "--force"],
                    cwd=self.root, capture_output=True, text=True, timeout=180
                )
                push_result[0] = result
                push_complete[0] = True
            except subprocess.TimeoutExpired:
                push_complete[0] = True
                push_result[0] = None
            except Exception as e:
                push_complete[0] = True
                push_result[0] = e

        push_thread = threading.Thread(target=do_push)
        push_thread.daemon = True
        push_thread.start()

        dots = 0
        while not push_complete[0]:
            dots = (dots + 1) % 4
            print(f"\rPushing{' .' * dots}   ", end="", flush=True)
            time.sleep(0.5)
        print("\r" + " " * 30 + "\r", end="", flush=True)

        if push_result[0] is None:
            self.log("Push timed out after 3 minutes", "ERROR")
            return False
        if isinstance(push_result[0], Exception):
            self.log(f"Push error: {push_result[0]}", "ERROR")
            return False

        result = push_result[0]
        if result.returncode == 0:
            self.log("Push successful!", "SUCCESS")
            return True

        error = result.stderr.strip() or result.stdout.strip()
        if self.token in error:
            error = error.replace(self.token, "[TOKEN_HIDDEN]")
        self.log(f"Push failed: {error}", "ERROR")
        return False

    def run(self):
        print("\n" + "=" * 60)
        print("WG-PANEL - Push Source to GitHub")
        print("=" * 60)

        if not self.check_git():
            sys.exit(1)

        if not self.root.exists():
            self.log(f"Directory not found: {self.root}", "ERROR")
            sys.exit(1)

        if not self.get_credentials():
            sys.exit(1)

        if self.push_to_github():
            print(f"\nSuccessfully pushed to: {self.repo_url}")
        else:
            self.log("Push failed.", "ERROR")
            sys.exit(1)


def main():
    try:
        pusher = GitHubPusher()
        pusher.run()
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
