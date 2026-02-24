#!/usr/bin/env python3

import os
import csv
import gitlab
from pathlib import Path

GITLAB_URL = "https://gitlab.com"


def extract_gitlab_metadata(output_file="gitlab_migration_inventory.csv"):

    gitlab_token = os.getenv("GITLAB_TOKEN")
    if not gitlab_token:
        print("❌ Error: GITLAB_TOKEN environment variable not set.")
        return

    print("🔍 Connecting to GitLab...")
    gl = gitlab.Gitlab(GITLAB_URL, private_token=gitlab_token)

    headers = [
        "Full Group Path",
        "Repository Name",
        "Repository URL",
        "Status",
        "Is Empty",
        "Visibility",
        "Last Activity",
        "Size (MB)",
        "Wiki Enabled",
        "Pipelines Exist",
        "Branch Count",
        "Primary Language"
    ]

    projects = gl.projects.list(owned=True, statistics=True, all=True)

    if not projects:
        print("⚠ No projects found.")
        return

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()

        for proj in projects:
            try:
                stats = getattr(proj, "statistics", {}) or {}

                # Check pipelines
                pipelines_exist = False
                try:
                    proj.files.get(file_path=".gitlab-ci.yml", ref=proj.default_branch)
                    pipelines_exist = True
                except:
                    pass

                languages = proj.languages()
                primary_lang = (
                    max(languages, key=languages.get)
                    if languages else "N/A"
                )

                branch_count = 0
                if not proj.empty_repo:
                    branch_count = len(proj.branches.list(all=True))

                data = {
                    "Full Group Path": proj.namespace["full_path"],
                    "Repository Name": proj.name,
                    "Repository URL": proj.web_url,
                    "Status": "Archived" if proj.archived else "Active",
                    "Is Empty": proj.empty_repo,
                    "Visibility": proj.visibility,
                    "Last Activity": proj.last_activity_at,
                    "Size (MB)": round(stats.get("repository_size", 0) / 1024 / 1024, 2),
                    "Wiki Enabled": proj.wiki_enabled,
                    "Pipelines Exist": pipelines_exist,
                    "Branch Count": branch_count,
                    "Primary Language": primary_lang,
                }

                writer.writerow(data)
                print(f"✅ Processed: {proj.path_with_namespace}")

            except Exception as e:
                print(f"❌ Error processing {proj.name}: {e}")

    print(f"\n🎯 Success! Metadata saved to {output_file}")


if __name__ == "__main__":
    extract_gitlab_metadata()