
import os
import sys
import requests

from pathlib import Path
from collections import Counter
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


# -----------------------------------------
# CONFIGURATION
# -----------------------------------------

TOKEN = os.environ.get("SONAR_TOKEN")
PROJECT = os.environ.get("SONAR_PROJECT_KEY")

BRANCH = os.environ.get("SONAR_BRANCH", "")
PR_NUMBER = os.environ.get("SONAR_PR", "")
COMMIT = os.environ.get("GITHUB_SHA", "Unknown")

API_URL = "https://sonarcloud.io/api/issues/search"

if not TOKEN:
    sys.exit("ERROR: SONAR_TOKEN is missing.")

if not PROJECT:
    sys.exit("ERROR: SONAR_PROJECT_KEY is missing.")


# -----------------------------------------
# SONARQUBE API REQUEST
# -----------------------------------------

headers = {
    "Authorization": f"Bearer {TOKEN}"
}

params = {
    "componentKeys": PROJECT,
    "resolved": "false",
    "ps": 500,
    "p": 1
}

if PR_NUMBER:
    params["pullRequest"] = PR_NUMBER

elif BRANCH and BRANCH != "main":
    params["branch"] = BRANCH


issues = []

while True:
    response = requests.get(
        API_URL,
        headers=headers,
        params=params,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    batch = data.get("issues", [])
    issues.extend(batch)

    total = data.get("paging", {}).get("total", 0)

    if len(issues) >= total or not batch:
        break

    params["p"] += 1


# -----------------------------------------
# CREATE EXCEL WORKBOOK
# -----------------------------------------

workbook = Workbook()

summary = workbook.active
summary.title = "Summary"

summary.append(["SonarQube Analysis Report"])
summary.append(["Project", PROJECT])
summary.append(["Branch", BRANCH or "N/A"])
summary.append(["Pull Request", PR_NUMBER or "N/A"])
summary.append(["Commit SHA", COMMIT])
summary.append(["Total Open Issues", len(issues)])
summary.append([])

summary.append(["Severity", "Count"])

severity_counts = Counter(
    issue.get("severity", "UNKNOWN").upper()
    for issue in issues
)

for severity in [
    "BLOCKER",
    "CRITICAL",
    "MAJOR",
    "MINOR",
    "INFO"
]:
    summary.append([
        severity,
        severity_counts.get(severity, 0)
    ])


summary.append([])
summary.append(["Issue Type", "Count"])

type_counts = Counter(
    issue.get("type", "UNKNOWN")
    for issue in issues
)

for issue_type, count in sorted(type_counts.items()):
    summary.append([issue_type, count])


# -----------------------------------------
# DETAILED ISSUES WORKSHEET
# -----------------------------------------

sheet = workbook.create_sheet("All Issues")

columns = [
    "Issue Key",
    "Severity",
    "Type",
    "Message",
    "File",
    "Line",
    "Rule",
    "Status",
    "Assignee",
    "Author",
    "Created Date"
]

sheet.append(columns)

for issue in issues:

    component = issue.get("component", "")

    # Keep the full component path. The Taiga integration
    # will extract the repository-relative file path.
    sheet.append([
        issue.get("key", ""),
        issue.get("severity", ""),
        issue.get("type", ""),
        issue.get("message", ""),
        component,
        issue.get("line", ""),
        issue.get("rule", ""),
        issue.get("status", ""),
        issue.get("assignee", ""),
        issue.get("author", ""),
        issue.get("creationDate", "")
    ])


# -----------------------------------------
# FORMAT EXCEL WORKSHEETS
# -----------------------------------------

for ws in workbook.worksheets:

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for cell in ws[1]:

        cell.font = Font(
            bold=True,
            color="FFFFFF"
        )

        cell.fill = PatternFill(
            start_color="1F4E78",
            end_color="1F4E78",
            fill_type="solid"
        )

        cell.alignment = Alignment(
            wrap_text=True
        )

    for column in ws.columns:

        max_length = max(
            len(str(cell.value or ""))
            for cell in column
        )

        width = min(
            max(max_length + 2, 12),
            60
        )

        ws.column_dimensions[
            get_column_letter(column[0].column)
        ].width = width


# -----------------------------------------
# SAVE REPORT
# -----------------------------------------

output = Path("reports")
output.mkdir(exist_ok=True)

filename = output / "sonarqube-report.xlsx"

workbook.save(filename)

print(f"Excel report generated: {filename}")
print(f"Project: {PROJECT}")
print(f"Branch: {BRANCH}")
print(f"Commit: {COMMIT}")
print(f"Total issues: {len(issues)}")

print("\nSeverity summary:")

for severity, count in sorted(severity_counts.items()):
    print(f"{severity}: {count}")
