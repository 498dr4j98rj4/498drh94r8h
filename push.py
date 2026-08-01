#!/usr/bin/env python3
import subprocess
import sys
import os

def run_command(command, check=True):
    """Run a shell command and print its output."""
    print(f"Running: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if check and result.returncode != 0:
        print(f"Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    return result

def main():
    repo_url = "https://github.com/498dr4j98rj4/498drh94r8h.git"

    # Check if this is already a git repository
    if not os.path.isdir('.git'):
        print("Initializing git repository...")
        run_command(['git', 'init'])

    # Check if the remote 'origin' exists, if not add it, if it does, set the url
    remote_check = run_command(['git', 'remote', '-v'], check=False)
    if 'origin' not in remote_check.stdout:
        print(f"Adding remote origin: {repo_url}")
        run_command(['git', 'remote', 'add', 'origin', repo_url])
    else:
        print(f"Updating remote origin url to: {repo_url}")
        run_command(['git', 'remote', 'set-url', 'origin', repo_url])

    # Add all files
    print("Adding files...")
    run_command(['git', 'add', '.'])

    # Commit changes
    print("Committing changes...")
    # Check if there are changes to commit
    status = run_command(['git', 'status', '--porcelain'], check=False)
    if status.stdout.strip():
        run_command(['git', 'commit', '-m', 'Initial commit / Update source'])
    else:
        print("No changes to commit.")

    # Determine the current branch name (usually main or master)
    branch_result = run_command(['git', 'branch', '--show-current'], check=False)
    branch = branch_result.stdout.strip()

    if not branch:
        # If no branch is active (e.g., brand new repo), checkout 'main'
        branch = 'main'
        run_command(['git', 'checkout', '-b', branch], check=False)

    # Push to remote
    print(f"Pushing to {repo_url} on branch {branch}...")
    run_command(['git', 'push', '-u', 'origin', branch])

    print("Push complete!")

if __name__ == "__main__":
    main()
