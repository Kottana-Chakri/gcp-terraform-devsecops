import os
import sys
import requests
import pandas as pd

# ---------------- CONFIGURATION ----------------

TAIGA_URL = os.getenv("TAIGA_URL", "http://localhost:9000").rstrip("/")
TAIGA_TOKEN = os.getenv("TAIGA_TOKEN")

PROJECT_ID = 1
REPORT_PATH = "reports/sonarqube-report.xlsx"

# Taiga metadata IDs from your project
STATUS_NEW = 1
TYPE_BUG = 1

# SonarQube severity -> Taiga severity and priority
SEVERITY_MAPPING = {
    "BLOCKER": {"severity": 5, "priority": 3},
    "CRITICAL": {"severity": 5, "priority": 3},
    "MAJOR": {"severity": 4, "priority": 2},
}

# ------------------------------------------------

if not TAIGA_TOKEN:
    sys.exit("ERROR: TAIGA_TOKEN environment variable is not set.")

headers = {
    "Authorization": f"Bearer {TAIGA_TOKEN}",
    "Content-Type": "application/json",
}

session = requests.Session()
session.headers.update(headers)


def get_existing_issues():
    """Retrieve existing Taiga issues for this project."""
    url = f"{TAIGA_URL}/api/v1/issues"

    response = session.get(
        url,
        params={"project": PROJECT_ID, "page": 1, "page_size": 100},
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        return data.get("results", [])

    return data


def create_taiga_issue(row):
    """Create one Taiga issue from an Excel finding."""

    issue_key = str(row["Issue Key"]).strip()
    sonar_severity = str(row["Severity"]).strip().upper()
    mapping = SEVERITY_MAPPING[sonar_severity]

    subject = (
        f"[{sonar_severity}] "
        f"[SonarQube {issue_key}] "
        f"{str(row['Message']).strip()}"
    )

    description = f"""
Automatically created from the SonarQube Excel report.

SonarQube Issue Key: {issue_key}
Severity: {sonar_severity}
Type: {row['Type']}
Message: {row['Message']}

Repository file: {row['File']}
Line: {row['Line']}
Rule: {row['Rule']}
SonarQube status: {row['Status']}
Author: {row['Author']}

Please investigate and resolve this finding.
"""

    issue_body = {
        "project": PROJECT_ID,
        "subject": subject[:250],
        "description": description.strip(),
        "status": STATUS_NEW,
        "priority": mapping["priority"],
        "severity": mapping["severity"],
        "type": TYPE_BUG,
    }

    response = session.post(
        f"{TAIGA_URL}/api/v1/issues",
        json=issue_body,
        timeout=30,
    )
    response.raise_for_status()

    return response.json()


def main():
    if not os.path.exists(REPORT_PATH):
        sys.exit(f"ERROR: Excel report not found: {REPORT_PATH}")

    print("Reading SonarQube Excel report...")

    df = pd.read_excel(REPORT_PATH, sheet_name="All Issues")

    required_columns = {
        "Issue Key", "Severity", "Type", "Message",
        "File", "Line", "Rule", "Status", "Author"
    }

    missing = required_columns - set(df.columns)

    if missing:
        sys.exit(f"ERROR: Missing Excel columns: {sorted(missing)}")

    # Only create issues for BLOCKER, CRITICAL and MAJOR
    df["Severity"] = df["Severity"].astype(str).str.strip().str.upper()
    eligible = df[df["Severity"].isin(SEVERITY_MAPPING)].copy()

    print(f"Total findings in report: {len(df)}")
    print(f"Eligible findings: {len(eligible)}")

    print("Checking existing Taiga issues...")
    existing_issues = get_existing_issues()

    existing_keys = set()

    for issue in existing_issues:
        description = issue.get("description") or ""
        subject = issue.get("subject") or ""

        for key in eligible["Issue Key"].astype(str):
            if key in description or key in subject:
                existing_keys.add(key)

    created = 0
    skipped = 0

    for _, row in eligible.iterrows():
        issue_key = str(row["Issue Key"]).strip()

        if issue_key in existing_keys:
            print(f"SKIPPED (already exists): {issue_key}")
            skipped += 1
            continue

        try:
            issue = create_taiga_issue(row)
            print(
                f"CREATED: {issue_key} -> "
                f"Taiga issue #{issue.get('ref', issue.get('id'))}"
            )
            created += 1
            existing_keys.add(issue_key)

        except requests.RequestException as error:
            print(f"FAILED: {issue_key}: {error}")

    print("\n---------- SUMMARY ----------")
    print(f"Created: {created}")
    print(f"Skipped as duplicates: {skipped}")
    print("-----------------------------")


if __name__ == "__main__":
    main()