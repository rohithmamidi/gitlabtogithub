#!/usr/bin/env python3

import os
import gitlab
import argparse
import logging
import datetime
import csv
from github import Github

GITLAB_URL = "https://gitlab.com"


def log_and_print(message, level="info"):
    print(message)
    if level == "error":
        logging.error(message)
    else:
        logging.info(message)


def write_migration_summary(summary_file, gitlab_repo, github_repo, status):
    file_exists = os.path.isfile(summary_file)

    with open(summary_file, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["GitLab Repo", "GitHub Repo", "Migration Status"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow({
            "GitLab Repo": gitlab_repo,
            "GitHub Repo": github_repo,
            "Migration Status": status
        })


def migrate_metadata(gl_project, gh_repo):

    # ---------- LABELS ----------
    existing_labels = [label.name for label in gh_repo.get_labels()]
    for gl_label in gl_project.labels.list(all=True):
        if gl_label.name not in existing_labels:
            gh_repo.create_label(
                name=gl_label.name,
                color=gl_label.color.replace("#", ""),
                description=gl_label.description or ""
            )
            log_and_print(f"Created label: {gl_label.name}")

    # ---------- MILESTONES ----------
    existing_milestones = [ms.title for ms in gh_repo.get_milestones(state="all")]
    for gl_ms in gl_project.milestones.list(all=True):
        if gl_ms.title not in existing_milestones:
            gh_repo.create_milestone(
                title=gl_ms.title,
                state="open" if gl_ms.state == "active" else "closed",
                description=gl_ms.description or ""
            )
            log_and_print(f"Created milestone: {gl_ms.title}")

    # ---------- ISSUES ----------
    existing_issues = {issue.title: issue for issue in gh_repo.get_issues(state="all")}

    for gl_issue in gl_project.issues.list(all=True):
        if gl_issue.title not in existing_issues:
            gh_issue = gh_repo.create_issue(
                title=gl_issue.title,
                body=gl_issue.description or "",
                labels=gl_issue.labels or []
            )
            if gl_issue.state == "closed":
                gh_issue.edit(state="closed")

            log_and_print(f"Created issue: {gl_issue.title}")

    # ---------- MERGE REQUESTS → PR ----------
    existing_prs = [pr.title for pr in gh_repo.get_pulls(state="all")]

    for mr in gl_project.mergerequests.list(all=True):

        if mr.title in existing_prs:
            continue

        try:
            pr = gh_repo.create_pull(
                title=mr.title,
                body=(mr.description or "") +
                     f"\n\n(Migrated from GitLab MR !{mr.iid})",
                head=mr.source_branch,
                base=mr.target_branch
            )

            if mr.state in ["merged", "closed"]:
                pr.edit(state="closed")

            log_and_print(f"Created PR: {mr.title}")

        except Exception as e:
            log_and_print(f"Skipping MR {mr.title}: {e}", "error")


def main():

    parser = argparse.ArgumentParser(
        description="GitLab → GitHub Metadata Migration"
    )

    parser.add_argument("--gitlab-token", required=True)
    parser.add_argument("--github-token", required=True)
    parser.add_argument("--gitlab-project", required=True)
    parser.add_argument("--github-org", required=True)
    parser.add_argument("--github-repo", required=True)

    args = parser.parse_args()

    logging.basicConfig(
        filename="migration.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    # GitLab
    gl = gitlab.Gitlab(GITLAB_URL, private_token=args.gitlab_token)
    gl_project = gl.projects.get(args.gitlab_project)

    # GitHub
    gh = Github(args.github_token)

    try:
        gh_repo = gh.get_repo(f"{args.github_org}/{args.github_repo}")
    except:
        org = gh.get_organization(args.github_org)
        gh_repo = org.create_repo(args.github_repo, private=True)

    try:
        migrate_metadata(gl_project, gh_repo)
        write_migration_summary(
            "migration_summary.csv",
            args.gitlab_project,
            f"{args.github_org}/{args.github_repo}",
            "SUCCESS"
        )
        print("🎯 Metadata migration completed successfully.")

    except Exception as e:
        write_migration_summary(
            "migration_summary.csv",
            args.gitlab_project,
            f"{args.github_org}/{args.github_repo}",
            "FAILED"
        )
        print(f"❌ Migration failed: {e}")


if __name__ == "__main__":
    main()