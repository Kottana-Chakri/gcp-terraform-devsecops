
import os
import sys
import json
import re
import subprocess
from pathlib import Path

import pandas as pd
import requests


# =====================================================
# CONFIGURATION
# =====================================================

TAIGA_URL = os.getenv(
    "TAIGA_URL",
    "http://localhost:9000"
).rstrip("/")

TAIGA_TOKEN = os.getenv("TAIGA_TOKEN")

PROJECT_ID = int(
    os.getenv("TAIGA_PROJECT_ID", "1")
)

REPORT_PATH = Path(
    "reports/sonarqube-report.xlsx"
)

# Your existing Taiga project metadata.
STATUS_NEW = 1
TYPE_BUG = 1

# Taiga severity and priority mapping.
#
# BLOCKER -> Critical severity, High priority
# CRITICAL -> Critical severity, High priority
# MAJOR -> Important severity, Normal priority

SEVERITY_MAPPING = {
    "BLOCKER": {
        "severity": 5,
        "priority": 3
    },
    "CRITICAL": {
        "severity": 5,
        "priority": 3
    },
    "HIGH": {
        "severity": 5,
        "priority": 3
    },
    "MAJOR": {
        "severity": 4,
        "priority": 2
    },
    "MEDIUM": {
        "severity": 4,
        "priority": 2
    }
}

# Known developer mapping.
# Add other verified Git email -> Taiga user ID mappings
# through the TAIGA_USER_MAP GitHub variable.
DEFAULT_USER_MAP = {
    "chakri.kottana@qentelli.com": 6
}


# =====================================================
# VALIDATE CONFIGURATION
# =====================================================

if not TAIGA_TOKEN:
    sys.exit("ERROR: TAIGA_TOKEN environment variable is missing.")

if not REPORT_PATH.exists():
    sys.exit(f"ERROR: Excel report not found: {REPORT_PATH}")


# =====================================================
# DEVELOPER MAPPING
# =====================================================

def load_user_mapping():
    """
    Load Git email -> Taiga user ID mapping.

    Example JSON:
    {
        "chakri.kottana@qentelli.com": 6,
        "developer@example.com": 7
    }
    """

    mapping = DEFAULT_USER_MAP.copy()

    raw_mapping = os.getenv("TAIGA_USER_MAP", "").strip()

    if raw_mapping:
        try:
            configured = json.loads(raw_mapping)

            if not isinstance(configured, dict):
                raise ValueError("TAIGA_USER_MAP must be a JSON object.")

            for email, user_id in configured.items():
                normalized_email = str(email).strip().lower()
                normalized_id = int(user_id)

                if not normalized_email:
                    raise ValueError("Developer email cannot be empty.")

                if normalized_id <= 0:
                    raise ValueError("Taiga user IDs must be positive.")

                mapping[normalized_email] = normalized_id

        except (ValueError, TypeError, json.JSONDecodeError) as error:
            sys.exit(f"ERROR: Invalid TAIGA_USER_MAP: {error}")

    return mapping


USER_MAPPING = load_user_mapping()


# =====================================================
# TAIGA SESSION
# =====================================================

session = requests.Session()

session.headers.update({
    "Authorization": f"Bearer {TAIGA_TOKEN}",
    "Content-Type": "application/json"
})


# =====================================================
# READ EXCEL REPORT
# =====================================================

def read_report():

    print("\nReading SonarQube Excel report...")

    summary = pd.read_excel(
        REPORT_PATH,
        sheet_name="Summary",
        header=None
    )

    issues_df = pd.read_excel(
        REPORT_PATH,
        sheet_name="All Issues"
    )

    required_columns = {
        "Issue Key",
        "Severity",
        "Type",
        "Message",
        "File",
        "Line",
        "Rule",
        "Status",
        "Author"
    }

    missing = required_columns - set(issues_df.columns)

    if missing:
        sys.exit(
            f"ERROR: Excel report missing columns: {sorted(missing)}"
        )

    commit_rows = summary[
        summary.iloc[:, 0].astype(str).str.strip() == "Commit SHA"
    ]

    if commit_rows.empty:
        sys.exit("ERROR: Commit SHA missing from Summary worksheet.")

    commit_sha = str(commit_rows.iloc[0, 1]).strip()

    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        sys.exit(
            f"ERROR: Invalid analyzed commit SHA: {commit_sha}"
        )

    issues_df["Severity"] = (
        issues_df["Severity"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    eligible = issues_df[
        issues_df["Severity"].isin(SEVERITY_MAPPING)
    ].copy()

    eligible["Issue Key"] = (
        eligible["Issue Key"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    eligible = eligible[
        eligible["Issue Key"] != ""
    ]

    eligible = eligible.drop_duplicates(
        subset=["Issue Key"]
    )

    print(f"Analyzed commit: {commit_sha}")
    print(f"Total report findings: {len(issues_df)}")
    print(f"Eligible findings: {len(eligible)}")

    return eligible, commit_sha


# =====================================================
# CHECK / FETCH ANALYZED COMMIT
# =====================================================

def ensure_commit_available(commit_sha):

    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("Analyzed commit is already available locally.")
        return

    print("Fetching analyzed commit from GitHub...")

    fetch = subprocess.run(
        ["git", "fetch", "--no-tags", "origin", commit_sha],
        capture_output=True,
        text=True
    )

    if fetch.returncode != 0:
        raise RuntimeError(
            "Could not fetch analyzed commit. "
            "Git output: " + fetch.stderr
        )

    check = subprocess.run(
        ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
        capture_output=True,
        text=True
    )

    if check.returncode != 0:
        raise RuntimeError(
            "Analyzed commit is still unavailable after fetching."
        )


# =====================================================
# FIND REPOSITORY FILE PATH
# =====================================================

def normalize_file_path(component):

    value = str(component).strip()

    # Sonar component often looks like:
    # organization_repository:path/to/file.tf
    #
    # Remove the project/component prefix.
    if ":" in value:
        value = value.rsplit(":", 1)[1]

    value = value.replace("\\", "/").lstrip("/")

    return value


# =====================================================
# GIT BLAME DEVELOPER IDENTIFICATION
# =====================================================

def identify_developer(file_path, line_number, commit_sha):

    if pd.isna(line_number):
        print("No source line available for Git blame.")
        return None

    try:
        line_number = int(line_number)
    except (ValueError, TypeError):
        print("Invalid source line number.")
        return None

    if line_number <= 0:
        return None

    file_path = normalize_file_path(file_path)

    if not file_path:
        return None

    command = [
        "git",
        "blame",
        "--line-porcelain",
        "-L",
        f"{line_number},{line_number}",
        commit_sha,
        "--",
        file_path
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.returncode != 0:
        print(
            f"Git blame unavailable for {file_path}:{line_number}: "
            f"{result.stderr.strip()}"
        )
        return None

    match = re.search(
        r"^author-mail <([^>]+)>$",
        result.stdout,
        re.MULTILINE
    )

    if not match:
        print("Git blame did not return an author email.")
        return None

    email = match.group(1).strip().lower()

    if email.startswith("unknown"):
        return None

    print(
        f"Git blame: {file_path}:{line_number} -> {email}"
    )

    return USER_MAPPING.get(email)


# =====================================================
# GET ALL EXISTING TAIGA ISSUES
# =====================================================

def get_existing_issues():

    print("\nRetrieving existing Taiga issues...")

    all_issues = []
    page = 1
    page_size = 100

    while True:

        response = session.get(
            f"{TAIGA_URL}/api/v1/issues",
            params={
                "project": PROJECT_ID,
                "page": page,
                "page_size": page_size
            },
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        if isinstance(data, dict):
            current_page = data.get("results", [])
        else:
            current_page = data

        if not current_page:
            break

        all_issues.extend(current_page)

        next_page = response.headers.get(
            "x-pagination-next"
        )

        if next_page:
            page += 1
            continue

        if len(current_page) < page_size:
            break

        page += 1

    print(f"Existing Taiga issues retrieved: {len(all_issues)}")

    return all_issues


# =====================================================
# DUPLICATE DETECTION
# =====================================================

def find_sonarqube_key(issue):

    description = issue.get("description") or ""
    subject = issue.get("subject") or ""

    combined = description + "\n" + subject

    match = re.search(
        r"SonarQube\s+(?:Issue Key:\s*)?([A-Za-z0-9_-]{10,})",
        combined,
        re.IGNORECASE
    )

    return match.group(1) if match else None


def build_existing_issue_map(existing_issues):

    issue_map = {}

    for issue in existing_issues:

        key = find_sonarqube_key(issue)

        if key:
            issue_map[key] = issue

    return issue_map


# =====================================================
# BUILD ISSUE DESCRIPTION
# =====================================================

def build_description(row, issue_key, commit_sha, developer_id):

    developer_text = (
        str(developer_id)
        if developer_id
        else "Not mapped to a Taiga account"
    )

    return f"""
Automatically synchronized from the SonarQube Excel report.

SonarQube Issue Key: {issue_key}

Severity: {row['Severity']}
Issue Type: {row['Type']}

Message:
{row['Message']}

File:
{row['File']}

Line:
{row['Line']}

Rule:
{row['Rule']}

SonarQube Status:
{row['Status']}

Report Author:
{row['Author']}

Analyzed Commit:
{commit_sha}

Git Blame Taiga User ID:
{developer_text}

Please investigate and resolve this finding.
""".strip()


# =====================================================
# CREATE TAIGA ISSUE
# =====================================================

def create_taiga_issue(row, commit_sha, developer_id):

    issue_key = str(row["Issue Key"]).strip()
    severity = str(row["Severity"]).strip().upper()

    mapping = SEVERITY_MAPPING[severity]

    subject = (
        f"[{severity}] "
        f"[SonarQube {issue_key}] "
        f"{str(row['Message']).strip()}"
    )

    issue_body = {
        "project": PROJECT_ID,
        "subject": subject[:250],
        "description": build_description(
            row,
            issue_key,
            commit_sha,
            developer_id
        ),
        "status": STATUS_NEW,
        "priority": mapping["priority"],
        "severity": mapping["severity"],
        "type": TYPE_BUG
    }

    if developer_id is not None:
        issue_body["assigned_to"] = developer_id

    response = session.post(
        f"{TAIGA_URL}/api/v1/issues",
        json=issue_body,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# =====================================================
# UPDATE EXISTING TAIGA ISSUE ASSIGNMENT
# =====================================================

def update_existing_assignment(issue, developer_id):

    if developer_id is None:
        return False

    if issue.get("assigned_to") == developer_id:
        return False

    issue_id = issue.get("id")
    version = issue.get("version")

    if not issue_id or version is None:
        print(
            f"Cannot safely update assignment for Taiga issue "
            f"{issue_id}: missing issue version."
        )
        return False

    payload = {
        "version": version,
        "assigned_to": developer_id
    }

    response = session.patch(
        f"{TAIGA_URL}/api/v1/issues/{issue_id}",
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    print(
        f"UPDATED assignment: Taiga issue #{issue_id} "
        f"-> user {developer_id}"
    )

    return True


# =====================================================
# MAIN AUTOMATION
# =====================================================

def main():

    print("=" * 55)
    print("SONARQUBE TO TAIGA AUTOMATION")
    print("=" * 55)

    eligible, commit_sha = read_report()

    if eligible.empty:
        print("No eligible findings. Nothing to synchronize.")
        return

    ensure_commit_available(commit_sha)

    existing_issues = get_existing_issues()

    existing_map = build_existing_issue_map(existing_issues)

    created = 0
    skipped = 0
    assigned = 0
    unassigned = 0
    failed = 0

    print("\nStarting Taiga synchronization...\n")

    for _, row in eligible.iterrows():

        issue_key = str(row["Issue Key"]).strip()

        print(f"\nProcessing: {issue_key}")

        try:

            developer_id = identify_developer(
                row["File"],
                row["Line"],
                commit_sha
            )

            if developer_id is None:
                print(
                    "No verified Taiga developer mapping found. "
                    "The issue will remain unassigned."
                )
                unassigned += 1

            existing_issue = existing_map.get(issue_key)

            if existing_issue:

                print(
                    f"Duplicate found: Taiga issue "
                    f"#{existing_issue.get('ref', existing_issue.get('id'))}"
                )

                if update_existing_assignment(
                    existing_issue,
                    developer_id
                ):
                    assigned += 1

                skipped += 1
                continue

            new_issue = create_taiga_issue(
                row,
                commit_sha,
                developer_id
            )

            issue_ref = new_issue.get(
                "ref",
                new_issue.get("id")
            )

            print(
                f"CREATED: SonarQube {issue_key} "
                f"-> Taiga issue #{issue_ref}"
            )

            if developer_id is not None:
                assigned += 1

            created += 1

            # Prevent duplicates within the same execution.
            existing_map[issue_key] = new_issue

        except requests.RequestException as error:

            print(
                f"TAIGA API ERROR for {issue_key}: {error}"
            )

            if error.response is not None:
                print(
                    "Response:",
                    error.response.text[:1000]
                )

            failed += 1

        except Exception as error:

            print(
                f"ERROR processing {issue_key}: {error}"
            )

            failed += 1

    print("\n" + "=" * 55)
    print("TAIGA SYNCHRONIZATION SUMMARY")
    print("=" * 55)

    print(f"Eligible findings: {len(eligible)}")
    print(f"Created: {created}")
    print(f"Existing duplicates: {skipped}")
    print(f"Assignment operations: {assigned}")
    print(f"Unassigned findings: {unassigned}")
    print(f"Failed: {failed}")

    print("=" * 55)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
