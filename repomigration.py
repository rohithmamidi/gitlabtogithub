#!/usr/bin/env python3

import os
import argparse
import subprocess
import tempfile
import shutil
import logging
import datetime
import csv
import time
import jwt
import requests
import gitlab
from github import Github
from github import Auth
from github.GithubException import GithubException

GITLAB_URL = "https://gitlab.com"
GITHUB_API = "https://api.github.com"
CURRENT_DATETIME = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


# =============================
# Utility
# =============================

def log_and_print(message, level="info"):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{level.upper()} {timestamp}] {message}")
    logging.info(message)


def load_repositories_from_file(path):
    repos = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            repo = line.strip()
            if repo:
                repos.append(repo)
    return repos


def write_migration_summary(path, gitlab_repo, github_repo, status):
    file_exists = os.path.isfile(path)

    with open(path, "a", newline="") as csvfile:
        fieldnames = ["GitLab Repo", "GitHub Repo", "Migration Status"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow({
            "GitLab Repo": gitlab_repo,
            "GitHub Repo": github_repo,
            "Migration Status": status
        })


# =============================
# GitHub App Token
# =============================

def generate_github_app_token(app_id, installation_id, private_key_path):

    with open(private_key_path, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": app_id
    }

    encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

    headers = {
        "Authorization": f"Bearer {encoded_jwt}",
        "Accept": "application/vnd.github+json"
    }

    url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"
    response = requests.post(url, headers=headers)

    if response.status_code != 201:
        raise Exception(f"GitHub App token error: {response.text}")

    return response.json()["token"]


# =============================
# Code Migration
# =============================

def migrate_code(gl_project, gh_repo, force=False):

    log_and_print("Starting mirror migration...")

    tmp_dir = tempfile.mkdtemp(prefix="repo_migration_")

    try:
        # Clone GitLab repo as mirror
        subprocess.run(
            ["git", "clone", "--mirror", gl_project.http_url_to_repo, tmp_dir],
            check=True
        )

        # Add GitHub remote
        subprocess.run(
            ["git", "remote", "add", "github", gh_repo.clone_url],
            cwd=tmp_dir,
            check=True
        )

        if force:
            log_and_print("Force push enabled — overwriting GitHub refs")
            subprocess.run(
                ["git", "push", "--mirror", "github"],
                cwd=tmp_dir,
                check=True
            )
        else:
            log_and_print("Pushing branches and tags")
            subprocess.run(
                ["git", "push", "github", "--all"],
                cwd=tmp_dir,
                check=True
            )
            subprocess.run(
                ["git", "push", "github", "--tags"],
                cwd=tmp_dir,
                check=True
            )

        log_and_print("Code migration completed", "success")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================
# MAIN
# =============================

def main():

    parser = argparse.ArgumentParser(description="GitLab → GitHub Repo Migration")

    parser.add_argument("--gitlab-token", required=True)
    parser.add_argument("--gitlab-project-file", required=True)
    parser.add_argument("--github-org", required=True)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--force", action="store_true")

    auth_group = parser.add_mutually_exclusive_group(required=True)
    auth_group.add_argument("--github-token")
    auth_group.add_argument("--use-app", action="store_true")

    parser.add_argument("--github-app-id")
    parser.add_argument("--github-installation-id")
    parser.add_argument("--github-private-key")

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    logging.basicConfig(
        filename=os.path.join(args.output_dir, f"migration_{CURRENT_DATETIME}.log"),
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True
    )

    # GitHub Authentication
    if args.use_app:
        if not (args.github_app_id and args.github_installation_id and args.github_private_key):
            parser.error("--use-app requires app id, installation id, private key")

        github_token = generate_github_app_token(
            args.github_app_id,
            args.github_installation_id,
            args.github_private_key
        )
        auth = Auth.Token(github_token)
        gh = Github(auth=auth)
    else:
        auth = Auth.Token(args.github_token)
        gh = Github(auth=auth)

    gl = gitlab.Gitlab(GITLAB_URL, private_token=args.gitlab_token)

    mappings = load_repositories_from_file(args.gitlab_project_file)

    summary_file = os.path.join(args.output_dir, f"repo_summary_{CURRENT_DATETIME}.csv")

    for mapping in mappings:

        if "::" not in mapping:
            log_and_print(f"Invalid mapping format: {mapping}", "error")
            continue

        gitlab_project_path, github_target = mapping.split("::")
        github_org, github_repo_name = github_target.split("/")

        log_and_print(f"Processing: {gitlab_project_path}")

        try:
            gl_project = gl.projects.get(gitlab_project_path)
        except Exception as e:
            log_and_print(f"GitLab fetch failed: {e}", "error")
            write_migration_summary(summary_file, gitlab_project_path, github_target, "failed")
            continue

        # Create or get GitHub repo
        try:
            gh_repo = gh.get_repo(f"{github_org}/{github_repo_name}")
            log_and_print("GitHub repo exists")
        except GithubException:
            try:
                org = gh.get_organization(github_org)
                gh_repo = org.create_repo(github_repo_name, private=True)
                log_and_print("Created repo in organization", "success")
            except GithubException:
                user = gh.get_user()
                gh_repo = user.create_repo(github_repo_name, private=True)
                log_and_print("Created repo in user account", "success")

        # Mirror Code
        try:
            migrate_code(gl_project, gh_repo, force=args.force)
            status = "success"
        except Exception as e:
            log_and_print(f"Migration failed: {e}", "error")
            status = "failed"

        write_migration_summary(summary_file, gitlab_project_path, github_target, status)

    log_and_print("All migrations completed", "success")


if __name__ == "__main__":
    main()