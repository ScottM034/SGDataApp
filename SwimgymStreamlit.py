import streamlit as st
import altair as alt
import pandas as pd
import numpy as np
import io
import re
import json
from datetime import datetime, date, timedelta

st.set_page_config(
    page_title="SwimGym Insights",
    page_icon="🏊",
    layout="wide"
)

# Ministry reference dates. Term 1 uses the earliest permitted start where
# schools had a choice; Term 4 uses the published latest end where applicable.
DEFAULT_TERM_DATES = pd.DataFrame([
    (2022, "Term 1", date(2022, 1, 31), date(2022, 4, 14)),
    (2022, "Term 2", date(2022, 5, 2), date(2022, 7, 8)),
    (2022, "Term 3", date(2022, 7, 25), date(2022, 9, 30)),
    (2022, "Term 4", date(2022, 10, 17), date(2022, 12, 20)),
    (2023, "Term 1", date(2023, 1, 30), date(2023, 4, 6)),
    (2023, "Term 2", date(2023, 4, 24), date(2023, 6, 30)),
    (2023, "Term 3", date(2023, 7, 17), date(2023, 9, 22)),
    (2023, "Term 4", date(2023, 10, 9), date(2023, 12, 20)),
    (2024, "Term 1", date(2024, 1, 29), date(2024, 4, 12)),
    (2024, "Term 2", date(2024, 4, 29), date(2024, 7, 5)),
    (2024, "Term 3", date(2024, 7, 22), date(2024, 9, 27)),
    (2024, "Term 4", date(2024, 10, 14), date(2024, 12, 20)),
    (2025, "Term 1", date(2025, 1, 27), date(2025, 4, 11)),
    (2025, "Term 2", date(2025, 4, 28), date(2025, 6, 27)),
    (2025, "Term 3", date(2025, 7, 14), date(2025, 9, 19)),
    (2025, "Term 4", date(2025, 10, 6), date(2025, 12, 19)),
    (2026, "Term 1", date(2026, 1, 26), date(2026, 4, 2)),
    (2026, "Term 2", date(2026, 4, 20), date(2026, 7, 3)),
    (2026, "Term 3", date(2026, 7, 20), date(2026, 9, 25)),
    (2026, "Term 4", date(2026, 10, 12), date(2026, 12, 18)),
    (2027, "Term 1", date(2027, 1, 28), date(2027, 4, 9)),
    (2027, "Term 2", date(2027, 4, 27), date(2027, 7, 2)),
    (2027, "Term 3", date(2027, 7, 19), date(2027, 9, 24)),
    (2027, "Term 4", date(2027, 10, 11), date(2027, 12, 17)),
    (2028, "Term 1", date(2028, 1, 31), date(2028, 4, 13)),
    (2028, "Term 2", date(2028, 5, 1), date(2028, 7, 7)),
    (2028, "Term 3", date(2028, 7, 24), date(2028, 9, 29)),
    (2028, "Term 4", date(2028, 10, 16), date(2028, 12, 15)),
], columns=["Year", "Term", "Start Date", "School End Date"])


def prepare_term_calendar(term_dates):
    calendar = term_dates.copy()
    calendar["Start Date"] = pd.to_datetime(calendar["Start Date"], errors="coerce")
    calendar["School End Date"] = pd.to_datetime(calendar["School End Date"], errors="coerce")
    valid = (
        calendar["Year"].notna() &
        calendar["Term"].notna() &
        calendar["Start Date"].notna() &
        calendar["School End Date"].notna() &
        (calendar["Start Date"] <= calendar["School End Date"])
    )
    calendar = calendar.loc[valid].copy()
    calendar["Swim End Date"] = calendar["School End Date"].apply(
        lambda end: end + timedelta(days=2) if end.weekday() == 4 else end
    )
    return calendar.sort_values(["Year", "Start Date"]).reset_index(drop=True)


_SHIFT_SCHEDULE_RE = re.compile(
    r"\b(Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\s*:?\s*-?\s*"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)\b",
    flags=re.IGNORECASE
)
_WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
INSTRUCTOR_INSIGHTS_PAGE = "Instructor Insights · BETA"
SHIFT_EDITOR_PAGE = "Shift Editor · BETA"


def scheduled_shifts(schedule):
    """Return (weekday index, start, end) tuples from a booking schedule string."""
    shifts = []
    for match in _SHIFT_SCHEDULE_RE.finditer(str(schedule or "")):
        day_index = _WEEKDAY_INDEX[match.group(1)[:3].lower()]
        start = re.sub(r"\s+", "", match.group(2)).upper()
        end = re.sub(r"\s+", "", match.group(3)).upper()
        shift = (day_index, start, end)
        if shift not in shifts:
            shifts.append(shift)
    return shifts


def instructor_name_for_insights(value):
    """Use the final First Last pair in iClassPro's concatenated Instructor field."""
    text = str(value or "").strip()
    if not text or text.casefold() in {"unknown", "nan", "none", "--", "-"}:
        return "Unknown"
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(
        r"\bTo\s+be\s+Confirmed\b|\bTo\s+Be\s+Covered\b|\bTo\s+Be\s+Advised\b|\bTBC\b",
        " ", text, flags=re.IGNORECASE
    )
    tokens = re.findall(r"[A-Za-z][A-Za-z'’.-]*", text)
    if len(tokens) < 2:
        return "Unknown"
    name = " ".join(tokens[-2:]).strip(" .,-")
    if name.casefold() in {"unknown", "to confirmed", "be covered"} or name == "--":
        return "Unknown"
    return name


def instructor_name_candidates(value):
    """Names in the concatenated field, used as choices for a manual override."""
    text = re.sub(r"\([^)]*\)", " ", str(value or ""))
    text = re.sub(
        r"\bTo\s+be\s+Confirmed\b|\bTo\s+Be\s+Covered\b|\bTo\s+Be\s+Advised\b|\bTBC\b",
        " ", text, flags=re.IGNORECASE
    )
    tokens = re.findall(r"[A-Za-z][A-Za-z'’.-]*", text)
    return {
        f"{tokens[index]} {tokens[index + 1]}"
        for index in range(0, len(tokens) - 1, 2)
    }


def shift_override_key(term_start, term_end, location, class_name, weekday, start_time, end_time):
    return json.dumps([
        pd.Timestamp(term_start).date().isoformat(), pd.Timestamp(term_end).date().isoformat(),
        str(location), str(class_name), int(weekday), str(start_time), str(end_time)
    ], ensure_ascii=False, separators=(",", ":"))


def load_shift_overrides():
    payload = st.session_state.get("instructor_shift_overrides", {})
    return dict(payload) if isinstance(payload, dict) else {}


def save_shift_overrides(overrides):
    # Keep only deliberate corrections in this browser session.
    compact = {key: value for key, value in overrides.items() if value}
    st.session_state["instructor_shift_overrides"] = compact


def open_shift_editor():
    # This runs as a widget callback, before the dashboard radio is rebuilt.
    st.session_state["dashboard_page"] = SHIFT_EDITOR_PAGE


@st.cache_data(show_spinner=False)
def instructor_shift_editor_data(df, term_start, term_end, overrides):
    term_start = pd.Timestamp(term_start)
    term_end = pd.Timestamp(term_end)
    active = df[
        df["Start Date"].notna() &
        (df["Start Date"] <= term_end) &
        (df["End Date"].isna() | (df["End Date"] >= term_start)) &
        df["Class Name"].fillna("").astype(str).str.strip().ne("")
    ]
    grouped = {}
    term_staff = set()
    for _, row in active.iterrows():
        instructor_name = instructor_name_for_insights(row.get("Instructor", ""))
        term_staff.update(instructor_name_candidates(row.get("Instructor", "")))
        if instructor_name != "Unknown":
            term_staff.add(instructor_name)
        class_name = str(row.get("Class Name", "") or "").strip()
        location = str(row.get("Location", "") or "").strip()
        student_id = str(row.get("StudentID", "") or "").strip()
        for weekday, start_time, end_time in scheduled_shifts(row.get("Schedule", "")):
            key = shift_override_key(term_start, term_end, location, class_name,
                                     weekday, start_time, end_time)
            entry = grouped.setdefault(key, {
                "Location": location, "Class": class_name,
                "Level": str(row.get("Level", "") or ""),
                "Weekday": weekday, "Day": _WEEKDAY_NAMES[weekday],
                "Start": start_time, "End": end_time,
                "Instructor Counts": {}, "Students": set()
            })
            if instructor_name != "Unknown":
                entry["Instructor Counts"][instructor_name] = (
                    entry["Instructor Counts"].get(instructor_name, 0) + 1
                )
            if student_id:
                entry["Students"].add(student_id)

    editor_rows = []
    for key, entry in grouped.items():
        instructors = sorted(entry["Instructor Counts"])
        # Each row uses its final First Last pair. If student rows disagree,
        # use the most common parsed pair for this shift as the default.
        default = (
            sorted(instructors, key=lambda name: (-entry["Instructor Counts"][name], name))[0]
            if instructors else "Needs review"
        )
        entry["Shift Key"] = key
        entry["Inferred Default"] = default
        entry["Students"] = len(entry["Students"])
        entry["Instructor Options"] = instructors
        entry["Assignment"] = overrides.get(key, "Use inferred")
        editor_rows.append(entry)

    options = sorted(term_staff | {
        value for key, value in overrides.items()
        if value and key in grouped
    })
    return editor_rows, options

# -------------------------
# PROCESS DATA (CLEAN)
# -------------------------
@st.cache_data(ttl=300)
def process_data(full_list, lep_data_uploaded=False):
    full_list = full_list.copy()
    full_list["Class Name"] = full_list["Class/Camp/Appointment"].fillna("").astype(str).str.strip()

    # Fix locations only for rows that originally came from Sites.
    if "Class/Camp/Appointment" in full_list.columns:
        mask_sites = full_list["Location"].eq("Sites")
        text_col = full_list.loc[mask_sites, "Class/Camp/Appointment"].fillna("").astype(str)

        for code, location in [("PAP", "PAP"), ("WAI", "WAI"), ("OT", "OT"), ("MBS", "MBS")]:
            full_list.loc[mask_sites & text_col.str.contains(code, case=False, na=False), "Location"] = location

    # Dates
    start_drop = full_list["Start/Drop Date"].fillna("").astype(str)
    full_list["Start Date"] = pd.to_datetime(
        start_drop.str.slice(6, 16),
        format="%d/%m/%Y",
        errors="coerce"
    )
    full_list["End Date"] = pd.to_datetime(
        start_drop.str.slice(21, 31),
        format="%d/%m/%Y",
        errors="coerce"
    )

    full_list = full_list.drop(
        columns=["Start/Drop Date", "Class/Camp/Appointment"],
        errors="ignore"
    )

    # One CSV row = one booking. Therefore Time Spent is calculated for EACH
    # booking row and is deliberately NOT deduplicated later when summing time.
    now = pd.Timestamp(datetime.now())
    full_list["Time Spent"] = (
        full_list["End Date"].fillna(now) - full_list["Start Date"]
    ).dt.days
    full_list["Time Spent"] = full_list["Time Spent"].clip(lower=0).fillna(0)

    # Student information
    full_list["Birthday"] = pd.to_datetime(full_list["Birthday"], errors="coerce")

    student_name = (
        full_list["Student"].fillna("").astype(str).str.strip().str.casefold()
    )
    guardian = (
        full_list["Guardian 1"].fillna("").astype(str).str.strip().str.casefold()
    )
    birthday = full_list["Birthday"].dt.strftime("%Y-%m-%d").fillna("")

    # Canonical identity used everywhere else in the app.
    full_list["StudentID"] = student_name + " / " + birthday + " / " + guardian

    full_list["Age"] = (now - full_list["Birthday"]).dt.days / 365.25

    # Passed means the student has a booking in the next level.
    passable_levels = {
        "Seahorse": ["Turtles"],
        "Seahorse Toddler": ["Turtles"],
        "Turtles": ["Octopus"],
        "Octopus": [],
        "Starfish": ["Shrimp"],
        "Shrimp": ["Otters"],
        "Otters": ["Penguins"],
        "Penguins": ["Sharks"],
        "Sharks": [],
        "New Swimmers": ["Moving and Stroking"],
        "Moving and Stroking": ["Breathers One"],
        "Breathers One": ["Breathers Two"],
        "Breathers Two": ["Improvers"],
        "Improvers": ["Howick Seals", "Seals"],
        "Howick Seals": ["Seals"],
        "Seals": ["Orcas"],
        "Orcas": ["Marlins"],
        "Marlins": ["Intro to Club", "Dolphins"],
        "Intro to Club": ["Dolphins"],
        "Adult Level 1": ["Adult Level 2"],
        "Adult Level 2": ["Adult Level 3"],
        "Teen New Swimmer": ["Teen Moving and Stroking"],
        "Teen Moving and Stroking": ["Teen Breathers"],
        "Teen Breathers": ["Teen Improvers"],
        "Teen Improvers": ["Seals"]
    }

    bookings = full_list[["StudentID", "Level"]].drop_duplicates()
    rows = []

    for _, row in bookings.iterrows():
        student = row["StudentID"]
        level = row["Level"]

        for next_level in passable_levels.get(level, []):
            rows.append((student, level, next_level))

    next_df = pd.DataFrame(
        rows,
        columns=["StudentID", "Level", "Next Level"]
    )

    if next_df.empty:
        full_list["Passed"] = False
    else:
        next_bookings = bookings.rename(columns={"Level": "Next Level"})
        passed_pairs = next_df.merge(
            next_bookings,
            on=["StudentID", "Next Level"],
            how="inner"
        )[["StudentID", "Level"]].drop_duplicates()

        passed_index = pd.MultiIndex.from_frame(
            passed_pairs[["StudentID", "Level"]]
        )
        full_index = pd.MultiIndex.from_frame(
            full_list[["StudentID", "Level"]]
        )
        full_list["Passed"] = full_index.isin(passed_index)

        # Howick Improvers can move into Howick Seals while waiting for a
        # Seals space. Count a direct Seals move from Howick only when LEP
        # data is included in this upload, so all general reports agree.
        howick_improvers = (
            full_list["Level"].eq("Improvers") &
            full_list["Location"].eq("Howick")
        )
        howick_targets = ["Howick Seals"]
        if lep_data_uploaded:
            howick_targets.append("Seals")
        has_howick_target = full_list["StudentID"].isin(
            full_list.loc[
                full_list["Level"].isin(howick_targets), "StudentID"
            ]
        )
        full_list.loc[howick_improvers, "Passed"] = has_howick_target.loc[howick_improvers]

    return full_list

st.title("SwimGym Insights")
st.subheader("Upload Location Data")
st.caption("Upload each location’s CSV export.")
upload_cols = st.columns(3)
with upload_cols[0]:
    lep_file = st.file_uploader("LEP Location File", type="csv", key="lep_location_upload", help="The file should contain the LEP location code.")
    st.caption("File code: LEP")
with upload_cols[1]:
    howick_file = st.file_uploader("Howick Location File", type="csv", key="howick_location_upload", help="The file should contain the HWK location code.")
    st.caption("File code: HWK")
with upload_cols[2]:
    sites_file = st.file_uploader("Sites Location File", type="csv", key="sites_location_upload", help="The file should contain a site code such as PAP, WAI, OT or MBS.")
    st.caption("File codes: PAP · WAI · OT · MBS")

with st.expander("Review or edit school term dates", expanded=False):
    st.caption("Term dates are prefilled from 2022–2028. Friday school end dates extend to Sunday.")
    st.markdown("[Ministry of Education term dates](https://www.education.govt.nz/school-terms-and-holidays-dates)")
    term_date_editor = st.data_editor(
        DEFAULT_TERM_DATES,
        key="school_term_dates_editor",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "Year": st.column_config.NumberColumn("Year", min_value=2022, max_value=2100, step=1, format="%d"),
            "Term": st.column_config.TextColumn("Term", help="For example, Term 1"),
            "Start Date": st.column_config.DateColumn("Term starts", format="YYYY-MM-DD"),
            "School End Date": st.column_config.DateColumn("School term ends", format="YYYY-MM-DD")
        }
    )
term_calendar = prepare_term_calendar(term_date_editor)
if len(term_calendar) < len(term_date_editor):
    st.warning("Incomplete or invalid term date rows are ignored.")
st.divider()

dataframes = []

# Load booking data. The CSVs use the column name "Instructor".
REQUIRED_COLUMNS = [
    "Student", "Birthday", "Gender", "Guardian 1", "Level",
    "Start/Drop Date", "Schedule", "Instructor"
]
BOOKING_TYPE_COLUMNS = ["Class/Camp/Appointment", "Class/Event/Appointment"]

@st.cache_data(show_spinner=False)
def _load_booking_bytes(csv_bytes, location):
    data = pd.read_csv(io.BytesIO(csv_bytes))
    expected_codes = {
        "LEP": ["LEP"],
        "Howick": ["HWK"],
        "Sites": ["PAP", "WAI", "OT", "MBS"]
    }[location]
    code_pattern = re.compile(
        r"(?<![A-Z0-9])(?:" + "|".join(expected_codes) + r")(?![A-Z0-9])",
        flags=re.IGNORECASE
    )
    cell_values = data.fillna("").astype(str).to_numpy().ravel()
    if not any(code_pattern.search(value) for value in cell_values):
        expected = ", ".join(expected_codes)
        raise ValueError(f"The file uploaded as {location} does not contain an expected location code ({expected}). Check that it is the correct export.")

    missing = [c for c in REQUIRED_COLUMNS if c not in data.columns]
    if missing:
        raise ValueError(f"{location} CSV is missing required column(s): {', '.join(missing)}")

    present_type_columns = [column for column in BOOKING_TYPE_COLUMNS if column in data.columns]
    if not present_type_columns:
        expected = " or ".join(f'"{column}"' for column in BOOKING_TYPE_COLUMNS)
        raise ValueError(f"{location} CSV is missing the booking type column ({expected}).")

    if "Class/Camp/Appointment" not in data.columns:
        data = data.rename(columns={"Class/Event/Appointment": "Class/Camp/Appointment"})
    elif "Class/Event/Appointment" in data.columns:
        data["Class/Camp/Appointment"] = data["Class/Camp/Appointment"].fillna(
            data["Class/Event/Appointment"]
        )

    data = data[REQUIRED_COLUMNS + ["Class/Camp/Appointment"]].copy()
    data["Instructor"] = data["Instructor"].fillna("Unknown").astype(str).str.strip()
    data.loc[data["Instructor"].isin(["", "nan", "None"]), "Instructor"] = "Unknown"
    data["Location"] = location
    return data


def load_booking_file(uploaded_file, location):
    return _load_booking_bytes(uploaded_file.getvalue(), location)


if lep_file is not None:
    try:
        dataframes.append(load_booking_file(lep_file, "LEP"))
    except ValueError as e:
        st.error(str(e))

if howick_file is not None:
    try:
        dataframes.append(load_booking_file(howick_file, "Howick"))
    except ValueError as e:
        st.error(str(e))

if sites_file is not None:
    try:
        dataframes.append(load_booking_file(sites_file, "Sites"))
    except ValueError as e:
        st.error(str(e))


# Stop if no valid data was uploaded.
if not dataframes:
    st.warning("Please upload at least one CSV file to use the app.")
    st.stop()

# ✅ Build dataset
full_list = pd.concat(dataframes, ignore_index=True)
lep_data_uploaded = full_list["Location"].eq("LEP").any()
full_list = process_data(full_list, lep_data_uploaded)
LEP_DATA_UPLOADED = lep_data_uploaded

genders = ["Male", "Female"]
location_order = ["LEP", "Howick", "PAP", "WAI", "OT", "MBS"]
available_locations = [
    location for location in location_order
    if full_list["Location"].eq(location).any()
]
available_locations += sorted(
    set(full_list["Location"].dropna().astype(str).unique()) - set(location_order)
)
locations = available_locations + ["Total"]

all_levels = ["Seahorse","Seahorse Toddler","Turtles","Octopus","Starfish","Shrimp","Otters","Penguins",
              "Sharks","New Swimmers","Moving and Stroking","Breathers One","Breathers Two","Improvers",
              "Howick Seals","Seals","Orcas","Marlins","Intro to Club","Dolphins","Fundamental Skills",
              "Junior Olympians","Development","Junior Performance","Youth Performance","Open Performance",
              "Open Development","Adult Level 1","Adult Level 2","Adult Level 3","Teen New Swimmer",
              "Teen Moving and Stroking","Teen Breathers","Teen Improvers"]

# -------------------------
# LEVEL SUMMARY FUNCTION
# -------------------------
@st.cache_data(show_spinner=False)
def student_lookup_options(df):
    options = (
        df[["StudentID", "Student", "Birthday", "Guardian 1"]]
        .drop_duplicates("StudentID")
        .sort_values("Student")
    )
    labels = {}
    for row in options.itertuples(index=False):
        birthday = row.Birthday.strftime("%d/%m/%Y") if pd.notna(row.Birthday) else "Unknown DOB"
        labels[row.StudentID] = f"{row.Student} — {birthday}"
    return options, labels


@st.cache_data(ttl=300, show_spinner=False)
def level_summary(df, level, total_only=False):
    # Current bookings only. Every row is a booking, so time is summed across
    # all current bookings belonging to the same student and level.
    current = df[(df["End Date"].isna()) & (df["Level"] == level)].copy()

    if current.empty:
        columns = ["Location", "Students", "Average Age", "Average Weeks in Level"] if total_only else ["Location", "Gender", "Students", "Average Age", "Average Weeks in Level"]
        return pd.DataFrame(columns=columns)

    current["Booking Weeks"] = ((pd.Timestamp(datetime.now()) - current["Start Date"]).dt.days / 7).clip(lower=0)

    def aggregate(temp, group_cols):
        if temp.empty:
            return 0, np.nan, np.nan

        grouped = temp.groupby(group_cols, as_index=False).agg(
            Age=("Age", "first"),
            Weeks=("Booking Weeks", "sum")
        )
        return len(grouped), grouped["Age"].mean(), grouped["Weeks"].mean()

    results = []

    for loc in locations:
        temp = current if loc == "Total" else current[current["Location"] == loc]

        if total_only:
            count, avg_age, avg_weeks = aggregate(temp, ["StudentID"])
            if pd.notna(avg_age):
                years = int(avg_age)
                months = int((avg_age - years) * 12)
                age_str = f"{years}y {months}m"
            else:
                age_str = "-"

            results.append({
                "Location": loc,
                "Students": count,
                "Average Age": age_str,
                "Average Weeks in Level": round(avg_weeks, 1) if pd.notna(avg_weeks) else "-"
            })
        else:
            for gender in genders:
                gender_temp = temp[temp["Gender"] == gender]
                count, avg_age, avg_weeks = aggregate(gender_temp, ["StudentID"])

                if pd.notna(avg_age):
                    years = int(avg_age)
                    months = int((avg_age - years) * 12)
                    age_str = f"{years}y {months}m"
                else:
                    age_str = "-"

                results.append({
                    "Location": loc,
                    "Gender": gender,
                    "Students": count,
                    "Average Age": age_str,
                    "Average Weeks in Level": round(avg_weeks, 1) if pd.notna(avg_weeks) else "-"
                })

    return pd.DataFrame(results)


@st.cache_data(show_spinner=False)
def time_spent_summary(df, start_date, end_date, level, total_only=False):
    # Only completed bookings that ended inside the selected period.
    temp_base = df[
        (df["Passed"] == True) &
        (df["Level"] == level) &
        (df["End Date"].notna()) &
        (df["End Date"] >= pd.to_datetime(start_date)) &
        (df["End Date"] <= pd.to_datetime(end_date))
    ].copy()

    temp_base["Booking Weeks"] = temp_base["Time Spent"] / 7
    results = []

    for loc in locations:
        temp = temp_base if loc == "Total" else temp_base[temp_base["Location"] == loc]

        if total_only:
            grouped = temp.groupby("StudentID", as_index=False)["Booking Weeks"].sum()
            n = len(grouped)
            avg = grouped["Booking Weeks"].mean() if n else 0

            results.append({
                "Location": loc,
                "Average Weeks": round(avg, 1),
                "Students": n
            })
        else:
            for gender in genders:
                gender_temp = temp[temp["Gender"] == gender]
                grouped = gender_temp.groupby("StudentID", as_index=False)["Booking Weeks"].sum()
                n = len(grouped)
                avg = grouped["Booking Weeks"].mean() if n else 0

                results.append({
                    "Location": loc,
                    "Gender": gender,
                    "Average Weeks": round(avg, 1),
                    "Students": n
                })

    return pd.DataFrame(results)


@st.cache_data(show_spinner=False)
def yearly_summary(df, level, show_total_only, metric="Time Spent"):
    temp = df[
        (df["Passed"] == True) &
        (df["Level"] == level) &
        (df["End Date"].notna())
    ].copy()

    temp["Year"] = temp["End Date"].dt.year
    min_year = 2020
    max_year = datetime.now().year
    results = []

    for year in range(min_year, max_year + 1):
        year_df = temp[temp["Year"] == year].copy()

        if show_total_only:
            if metric == "Time Spent":
                grouped = year_df.groupby("StudentID", as_index=False)["Time Spent"].sum()
                value = round(grouped["Time Spent"].sum() / 7 / len(grouped), 2) if len(grouped) else 0
            else:
                value = year_df["StudentID"].nunique()

            results.append({
                "Year": year,
                "Gender": "Total",
                "Value": value,
                "Students": year_df["StudentID"].nunique()
            })
        else:
            for gender in genders:
                gender_df = year_df[year_df["Gender"] == gender]

                if metric == "Time Spent":
                    grouped = gender_df.groupby("StudentID", as_index=False)["Time Spent"].sum()
                    value = round(grouped["Time Spent"].sum() / 7 / len(grouped), 2) if len(grouped) else 0
                else:
                    value = gender_df["StudentID"].nunique()

                results.append({
                    "Year": year,
                    "Gender": gender,
                    "Value": value,
                    "Students": gender_df["StudentID"].nunique()
                })

    return pd.DataFrame(results)


@st.cache_data(show_spinner=False)
def run_group_analysis(df, locations, genders, start_date, end_date, selected_levels, total_only=False):
    temp_base = df[df["Passed"] == True].copy()

    if start_date is not None and end_date is not None:
        temp_base = temp_base[
            temp_base["End Date"].notna() &
            (temp_base["End Date"] >= pd.to_datetime(start_date)) &
            (temp_base["End Date"] <= pd.to_datetime(end_date))
        ]
    else:
        temp_base = temp_base[temp_base["End Date"].notna()]

    if selected_levels:
        temp_base = temp_base[temp_base["Level"].isin(selected_levels)]

    temp_base["Booking Weeks"] = temp_base["Time Spent"] / 7
    results = []

    for location in locations:
        temp = temp_base if location == "Total" else temp_base[temp_base["Location"] == location]

        if total_only:
            grouped = (
                temp.groupby(["StudentID", "Level"], as_index=False)["Booking Weeks"]
                .sum()
            )
            avg = grouped["Booking Weeks"].mean() if len(grouped) else 0

            results.append([location, round(avg, 1), len(grouped)])
        else:
            for gender in genders:
                gender_temp = temp[temp["Gender"] == gender]
                grouped = (
                    gender_temp.groupby(["StudentID", "Level"], as_index=False)["Booking Weeks"]
                    .sum()
                )
                avg = grouped["Booking Weeks"].mean() if len(grouped) else 0

                results.append([location, gender, round(avg, 1), len(grouped)])

    if total_only:
        return pd.DataFrame(results, columns=["Location", "Average Weeks", "Students"])
    return pd.DataFrame(results, columns=["Location", "Gender", "Average Weeks", "Students"])


@st.cache_data(show_spinner=False)
def build_yearly_export_tables(df):

    export_tables = []

    locations_export = locations
    genders_export = ["Both", "Male", "Female"]

    for location in locations_export:

        for gender in genders_export:

            temp = df.copy()

            if location != "Total":
                temp = temp[temp["Location"] == location]

            if gender != "Both":
                temp = temp[temp["Gender"] == gender]

            # -------------------------
            # Average Time Table
            # -------------------------

            time_rows = []

            for level in all_levels:

                level_df = yearly_summary(
                    temp,
                    level,
                    True,
                    metric="Time Spent"
                )

                if len(level_df) == 0:
                    continue

                row = {"Level": level}

                for _, r in level_df.iterrows():
                    row[int(r["Year"])] = r["Value"]

                time_rows.append(row)

            time_table = pd.DataFrame(time_rows)

            # -------------------------
            # Student Count Table
            # -------------------------

            count_rows = []

            for level in all_levels:

                level_df = yearly_summary(
                    temp,
                    level,
                    True,
                    metric="Students"
                )

                if len(level_df) == 0:
                    continue

                row = {"Level": level}

                for _, r in level_df.iterrows():
                    row[int(r["Year"])] = r["Value"]

                count_rows.append(row)

            count_table = pd.DataFrame(count_rows)

            def sort_year_columns(df):
                cols = ["Level"] + sorted(
                    [c for c in df.columns if c != "Level"],
                    key=lambda x: int(x)
                )
                return df.reindex(columns=cols)

            time_table = sort_year_columns(time_table)
            count_table = sort_year_columns(count_table)
            time_table = time_table.fillna(0)
            count_table = count_table.fillna(0)
            export_tables.append({
                "Location": location,
                "Gender": gender,
                "Time": time_table,
                "Students": count_table
            })

    return export_tables


@st.cache_data(ttl=300, show_spinner=False)
def students_at_risk(df, min_weeks, level_filter="All", day_filter="All"):
    # Only active bookings. Because one row is one booking, sum ALL active
    # booking durations for each student + level.
    active = df[df["End Date"].isna()].copy()

    active["Day"] = (
        active["Schedule"].fillna("").astype(str)
        .str.split(":").str[0].str.strip()
    )

    if level_filter != "All":
        active = active[active["Level"] == level_filter]

    if day_filter != "All":
        active = active[active["Day"] == day_filter]

    active["Booking Weeks"] = ((pd.Timestamp(datetime.now()) - active["Start Date"]).dt.days / 7).clip(lower=0)

    grouped = (
        active.groupby(["StudentID", "Level"], as_index=False)
        .agg(
            **{"Weeks In Level": ("Booking Weeks", "sum")},
            Locations=("Location", lambda x: ", ".join(sorted(set(x.dropna().astype(str))))),
            Days=("Day", lambda x: ", ".join(sorted(set(x.dropna().astype(str))))),
            Student=("Student", "first")
        )
    )

    grouped = grouped[grouped["Weeks In Level"] >= min_weeks]
    grouped = grouped.sort_values("Weeks In Level", ascending=False)

    return grouped[["StudentID", "Student", "Level", "Weeks In Level", "Locations", "Days"]]


@st.cache_data(show_spinner=False)
def schedule_day_options(df):
    return sorted(df["Schedule"].astype(str).str.split(":").str[0].dropna().unique())

# -------------------------
# INSTRUCTOR ANALYSIS
# -------------------------
PASSABLE_LEVELS = {
    "Seahorse": ["Turtles"], "Seahorse Toddler": ["Turtles"],
    "Turtles": ["Octopus"], "Starfish": ["Shrimp"], "Shrimp": ["Otters"],
    "Otters": ["Penguins"], "Penguins": ["Sharks"],
    "New Swimmers": ["Moving and Stroking"],
    "Moving and Stroking": ["Breathers One"],
    "Breathers One": ["Breathers Two"], "Breathers Two": ["Improvers"],
    "Improvers": ["Howick Seals", "Seals"], "Howick Seals": ["Seals"],
    "Seals": ["Orcas"], "Orcas": ["Marlins"],
    "Marlins": ["Intro to Club", "Dolphins"], "Intro to Club": ["Dolphins"],
    "Adult Level 1": ["Adult Level 2"], "Adult Level 2": ["Adult Level 3"],
    "Teen New Swimmer": ["Teen Moving and Stroking"],
    "Teen Moving and Stroking": ["Teen Breathers"],
    "Teen Breathers": ["Teen Improvers"], "Teen Improvers": ["Seals"]
}

INSTRUCTOR_PROGRAM_GROUPS = {
    "Babies": ["Seahorse", "Seahorse Toddler", "Turtles", "Octopus"],
    "Pre-school": ["Starfish", "Shrimp", "Otters", "Penguins", "Sharks"],
    "School-age": ["New Swimmers", "Moving and Stroking", "Breathers One", "Breathers Two", "Improvers"],
    "Mini Squads": ["Howick Seals", "Seals", "Orcas", "Marlins"]
}
MIN_INSTRUCTOR_GROUP_STUDENTS = 11


def instructor_for_booking(row, term_start, term_end, shift_overrides=None):
    shift_overrides = shift_overrides or {}
    end_date = row.get("End Date")
    class_name = row.get("Class Name", "")
    location = row.get("Location", "")
    if (pd.notna(end_date) and class_name and
            pd.Timestamp(term_start) <= pd.Timestamp(end_date) <= pd.Timestamp(term_end)):
        booking_end = pd.Timestamp(end_date).date()
        booking_start = pd.Timestamp(row.get("Start Date")).date()
        candidates = []
        for weekday, start_time, end_time in scheduled_shifts(row.get("Schedule", "")):
            last_meeting = booking_end - timedelta(days=(booking_end.weekday() - weekday) % 7)
            if last_meeting >= booking_start:
                candidates.append((last_meeting, start_time, weekday, start_time, end_time))
        if candidates:
            # Apply the correction for a single weekly shift regardless of
            # whether an enrollment drop date falls on its meeting weekday.
            _, _, weekday, start_time, end_time = max(candidates)
            key = shift_override_key(
                term_start, term_end, location, class_name, weekday, start_time, end_time
            )
            if key in shift_overrides:
                return shift_overrides[key]
    return instructor_name_for_insights(row.get("Instructor", ""))


@st.cache_data(show_spinner=False)
def instructor_records(df, start_date, end_date, shift_overrides=None):
    """Create one record per final instructor/student/level booking."""
    start_date = pd.Timestamp(start_date)
    end_date = pd.Timestamp(end_date)

    all_data = df.dropna(subset=["StudentID", "Level", "Start Date", "Instructor"]).copy()
    all_data["Instructor"] = all_data.apply(
        lambda row: instructor_for_booking(row, start_date, end_date, shift_overrides),
        axis=1
    )
    all_data = all_data[all_data["Instructor"].ne("Unknown")]
    data = all_data.dropna(subset=["End Date"]).copy()

    if data.empty:
        return pd.DataFrame()

    # The instructor is counted only for the booking(s) that end last in
    # this level. If there are tied final bookings, retain each instructor.
    final_dates = data.groupby(["StudentID", "Level"])["End Date"].transform("max")
    final_bookings = data[data["End Date"].eq(final_dates)].copy()

    # A move-up requires a booking in a permitted next level that starts on
    # or after the final booking in the previous level ends.
    next_bookings = df.dropna(subset=["StudentID", "Level", "Start Date"])
    next_starts = {
        (student, level): group["Start Date"].tolist()
        for (student, level), group in next_bookings.groupby(["StudentID", "Level"])
    }
    final_bookings["Moved Up"] = final_bookings.apply(
        lambda row: _instructor_booking_moved_up(row, next_starts),
        axis=1
    )

    # The selected period is based on when the final booking in the level ended.
    final_bookings = final_bookings[
        final_bookings["End Date"].between(start_date, end_date, inclusive="both")
    ].copy()
    if final_bookings.empty:
        return pd.DataFrame()

    # Sum all bookings for each instructor/student/level. This is important
    # when a student has multiple classes/bookings with the same instructor.
    booking_totals = (
        all_data.dropna(subset=["StudentID", "Level", "Instructor"])
        .groupby(["Instructor", "StudentID", "Level", "Location"], as_index=False)["Time Spent"]
        .sum()
        .rename(columns={"Time Spent": "Student Time Spent"})
    )

    # Only students who spent at least one week with this instructor in this level.
    eligible = booking_totals[booking_totals["Student Time Spent"] >= 7].copy()

    # Only the instructor on the final booking is assessed for this level.
    final_instructors = final_bookings[
        ["Instructor", "StudentID", "Level", "Location", "Moved Up"]
    ].drop_duplicates()
    records = eligible.merge(
        final_instructors,
        on=["Instructor", "StudentID", "Level", "Location"],
        how="inner"
    )
    return records


def _instructor_booking_moved_up(row, next_starts):
    next_levels = PASSABLE_LEVELS.get(row["Level"], [])
    if row["Level"] == "Improvers" and row["Location"] == "Howick":
        next_levels = ["Howick Seals"]
        if LEP_DATA_UPLOADED:
            next_levels.append("Seals")

    return any(
        any(
            next_start >= row["End Date"]
            for next_start in next_starts.get((row["StudentID"], next_level), [])
        )
        for next_level in next_levels
    )


@st.cache_data(show_spinner=False)
def instructor_summary(df, instructor, start_date, end_date, level_breakdown=True, records=None):
    if records is None:
        records = instructor_records(df, start_date, end_date)

    columns = [
        "Location", "Level", "Kids Moved Up", "Total Kids",
        "Time Spent Before Moving Up", "Move Up Percentage",
        "Time vs Location Avg", "Move Up % vs Location Avg",
        "Time vs All Teachers Avg", "Move Up % vs All Teachers Avg"
    ]
    if records.empty:
        return pd.DataFrame(columns=columns)

    group_cols = ["Location", "Level"] if level_breakdown else ["Location"]

    # For a level breakdown, each row is one location/level. For the location
    # view, all levels taught by the instructor are combined.
    def summarise(group):
        moved = group[group["Moved Up"]]
        student_times = moved["Student Time Spent"]
        return pd.Series({
            "Kids Moved Up": int(group["Moved Up"].sum()),
            "Total Kids": int(len(group)),
            "Time Spent Before Moving Up": student_times.mean() / 7 if len(student_times) else np.nan,
            "Move Up Percentage": group["Moved Up"].mean() * 100
        })

    # Build the same teacher-level metrics for comparison benchmarks.
    teacher_group_cols = ["Instructor", "Location", "Level"] if level_breakdown else ["Instructor", "Location"]
    teacher_stats = records.groupby(teacher_group_cols, sort=False).apply(summarise).reset_index()

    # Keep only the selected instructor for the displayed rows.
    records = records[records["Instructor"] == instructor].copy()
    if records.empty:
        return pd.DataFrame(columns=columns)

    result = records.groupby(group_cols, sort=False).apply(summarise).reset_index()

    if level_breakdown:
        location_avg = (
            teacher_stats.groupby(["Location", "Level"])[
                ["Time Spent Before Moving Up", "Move Up Percentage"]
            ].mean().reset_index()
            .rename(columns={
                "Time Spent Before Moving Up": "Location Time Avg",
                "Move Up Percentage": "Location Move Avg"
            })
        )
        all_avg = (
            teacher_stats.groupby("Level")[
                ["Time Spent Before Moving Up", "Move Up Percentage"]
            ].mean().reset_index()
            .rename(columns={
                "Time Spent Before Moving Up": "All Time Avg",
                "Move Up Percentage": "All Move Avg"
            })
        )
        result = result.merge(location_avg, on=["Location", "Level"], how="left")
        result = result.merge(all_avg, on="Level", how="left")
    else:
        location_avg = (
            teacher_stats.groupby("Location")[
                ["Time Spent Before Moving Up", "Move Up Percentage"]
            ].mean().reset_index()
            .rename(columns={
                "Time Spent Before Moving Up": "Location Time Avg",
                "Move Up Percentage": "Location Move Avg"
            })
        )
        all_avg = teacher_stats[
            ["Time Spent Before Moving Up", "Move Up Percentage"]
        ].mean()
        result = result.merge(location_avg, on="Location", how="left")
        result["All Time Avg"] = all_avg["Time Spent Before Moving Up"]
        result["All Move Avg"] = all_avg["Move Up Percentage"]
        result["Level"] = "All Levels"

    result["Time vs Location Avg"] = result["Time Spent Before Moving Up"] - result["Location Time Avg"]
    result["Move Up % vs Location Avg"] = result["Move Up Percentage"] - result["Location Move Avg"]
    result["Time vs All Teachers Avg"] = result["Time Spent Before Moving Up"] - result["All Time Avg"]
    result["Move Up % vs All Teachers Avg"] = result["Move Up Percentage"] - result["All Move Avg"]

    result = result[columns]

    if level_breakdown:
        level_order = {level: i for i, level in enumerate(PASSABLE_LEVELS)}
        result["_level_order"] = result["Level"].map(level_order).fillna(len(level_order))
        result = result.sort_values(["Location", "_level_order"]).drop(columns="_level_order")
    else:
        result = result.sort_values("Location")

    return result.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def instructor_leaderboard(records, min_students=MIN_INSTRUCTOR_GROUP_STUDENTS):
    if records.empty:
        return pd.DataFrame()

    per_student = (
        records.groupby(["Instructor", "StudentID"], as_index=False)["Moved Up"]
        .max()
    )
    overall = (
        per_student.groupby("Instructor", as_index=False)
        .agg(
            **{"Total Kids Moved Up": ("Moved Up", "sum")},
            **{"Students Assessed": ("StudentID", "nunique")}
        )
    )
    overall["Move Up Percentage"] = (
        overall["Total Kids Moved Up"] / overall["Students Assessed"] * 100
    )

    leaderboard = overall[
        overall["Students Assessed"] >= min_students
    ].copy()
    return leaderboard


@st.cache_data(show_spinner=False)
def instructor_location_distribution(records, min_students=MIN_INSTRUCTOR_GROUP_STUDENTS):
    if records.empty:
        return pd.DataFrame()

    per_student = (
        records.groupby(["Instructor", "Location", "StudentID"], as_index=False)["Moved Up"]
        .max()
    )
    distribution = (
        per_student.groupby(["Instructor", "Location"], as_index=False)
        .agg(
            **{"Students Assessed": ("StudentID", "nunique")},
            **{"Move Up Percentage": ("Moved Up", "mean")}
        )
    )
    distribution["Move Up Percentage"] *= 100
    return distribution[
        distribution["Students Assessed"] >= min_students
    ].copy()


def instructor_distribution_chart(distribution, locations):
    if distribution.empty:
        return None

    chart_locations = [
        location for location in locations
        if location in set(distribution["Location"].dropna())
    ]
    color_scale = alt.Scale(scheme="tableau10", domain=chart_locations)
    location_hover = alt.selection_point(
        fields=["Location"],
        on="pointerover",
        clear="pointerout",
        empty=True,
        toggle=False
    )

    legend_data = pd.DataFrame({"Location": chart_locations})
    location_labels = (
        alt.Chart(legend_data)
        .mark_text(align="left", baseline="middle", fontSize=13, dx=4)
        .encode(
            y=alt.Y("Location:N", sort=chart_locations, axis=None),
            text=alt.Text("Location:N"),
            color=alt.condition(
                location_hover,
                alt.Color("Location:N", scale=color_scale, legend=None),
                alt.value("#77808a")
            )
        )
        .add_params(location_hover)
        .properties(width=100, height=220)
    )

    distribution_chart = (
        alt.Chart(distribution)
        .transform_filter(location_hover)
        .mark_bar(opacity=0.85, stroke="white", strokeWidth=1)
        .encode(
            x=alt.X(
                "Move Up Percentage:Q",
                bin=alt.Bin(step=5),
                scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(values=[0, 20, 40, 60, 80, 100]),
                title="Average move-up percentage"
            ),
            xOffset=alt.XOffset("Location:N", sort=chart_locations),
            y=alt.Y("count():Q", stack=None, title="Number of instructors"),
            color=alt.Color("Location:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("Location:N", title="Location"),
                alt.Tooltip("count():Q", title="Instructors in range")
            ]
        )
        .properties(width=600, height=220)
    )

    return alt.hconcat(location_labels, distribution_chart, spacing=16).resolve_scale(color="shared")


def style_instructor_table(df):
    def comparison_style(value, higher_is_better=False):
        if pd.isna(value):
            return ""
        # For time, negative is better. For move-up %, positive is better.
        better = value > 0 if higher_is_better else value < 0
        worse = value < 0 if higher_is_better else value > 0
        if better:
            return "color: green; font-weight: bold;"
        if worse:
            return "color: red; font-weight: bold;"
        return ""

    styled = df.style.format({
        "Kids Moved Up": "{:.0f}",
        "Total Kids": "{:.0f}",
        "Time Spent Before Moving Up": "{:.1f}",
        "Move Up Percentage": "{:.1f}%",
        "Time vs Location Avg": "{:+.1f}",
        "Move Up % vs Location Avg": "{:+.1f}%",
        "Time vs All Teachers Avg": "{:+.1f}",
        "Move Up % vs All Teachers Avg": "{:+.1f}%"
    })

    styled = styled.map(
        lambda v: comparison_style(v, False),
        subset=["Time vs Location Avg", "Time vs All Teachers Avg"]
    )
    styled = styled.map(
        lambda v: comparison_style(v, True),
        subset=["Move Up % vs Location Avg", "Move Up % vs All Teachers Avg"]
    )
    return styled.set_table_styles([
        {"selector": "th", "props": [("white-space", "normal"), ("max-width", "100px")]},
        {"selector": "td", "props": [("white-space", "normal")]}
    ])


def term_move_counts(df, start_date, end_date):
    in_period = (
        df["End Date"].notna() &
        df["End Date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date), inclusive="both")
    )
    period_rows = df.loc[in_period, ["StudentID", "Location", "Passed"]].dropna(subset=["Location"])
    activity = period_rows.groupby("Location")["StudentID"].nunique().to_dict()
    moved = (
        period_rows[period_rows["Passed"] == True]
        .drop_duplicates(["Location", "StudentID"])
        .groupby("Location")["StudentID"]
        .nunique()
        .to_dict()
    )
    return activity, moved


def annual_move_projection(df, location):
    series = annual_moveup_timeseries(df, location=location)
    if series is None:
        return f"No current-year move-ups are recorded for {location}."
    year = series["year"]
    as_of = series["as_of"]
    current_moves = series["year_to_date"]
    if current_moves == 0:
        return f"No move-ups are recorded for {location} through {as_of:%d %b}."

    last_year_start = pd.Timestamp(year - 1, 1, 1)
    last_year_end = pd.Timestamp(year - 1, 12, 31)
    last_year_rows = df[
        df["Location"].eq(location) &
        df["End Date"].notna() &
        df["End Date"].between(last_year_start, last_year_end, inclusive="both")
    ]
    if last_year_rows.empty:
        return f"Not enough {year - 1} data to compare {location}'s current pace with last year."

    last_year_moves = int(series["year_totals"].get(str(year - 1), 0))
    if not series["has_forecast"]:
        return f"{location}: {current_moves} move-ups so far this year; {last_year_moves} last year."
    projection = round(series["projection"])
    difference = projection - last_year_moves

    if difference > 0:
        comparison = f"about {difference} more"
    elif difference < 0:
        comparison = f"about {abs(difference)} fewer"
    else:
        comparison = "about the same number"

    return (
        f"{location}: about {projection} move-ups projected this year, "
        f"{comparison} than last year ({last_year_moves}). Through {as_of:%d %b}."
    )


def latest_completed_term(df, calendar):
    latest_booking_date = df["Start Date"].dropna().max()
    if pd.isna(latest_booking_date):
        return None

    completed = calendar[calendar["Swim End Date"] < latest_booking_date.normalize()]
    if completed.empty:
        return None

    return completed.sort_values("Swim End Date").iloc[-1]


@st.cache_data(show_spinner=False)
def build_term_insights(df, calendar, shift_overrides=None):
    latest = latest_completed_term(df, calendar)
    if latest is None:
        return None, {"locations": [], "instructors": {}}

    year = int(latest["Year"])
    term = str(latest["Term"])
    previous = calendar[(calendar["Year"] == year - 1) & (calendar["Term"] == term)]
    title = f"{term} {year}"

    location_insights = []
    main_locations = ["LEP", "Howick", "PAP"]
    if previous.empty:
        for location in main_locations:
            location_insights.append({
                "Location": location,
                "Message": f"No {term} {year - 1} dates are available for comparison.",
                "Projection": annual_move_projection(df, location)
            })
    else:
        previous = previous.sort_values("Start Date").iloc[-1]
        current_activity, current_moves = term_move_counts(
            df, latest["Start Date"], latest["Swim End Date"]
        )
        prior_activity, prior_moves = term_move_counts(
            df, previous["Start Date"], previous["Swim End Date"]
        )
        uploaded_locations = set(df["Location"].dropna().astype(str))
        for location in main_locations:
            if location not in uploaded_locations:
                location_insights.append({
                    "Location": location,
                    "Message": f"Upload {location} data to show this comparison.",
                    "Projection": annual_move_projection(df, location)
                })
                continue
            if location not in current_activity or location not in prior_activity:
                location_insights.append({
                    "Location": location,
                    "Message": f"Not enough booking data to compare {term} {year} with {term} {year - 1}.",
                    "Projection": annual_move_projection(df, location)
                })
                continue
            current_count = int(current_moves.get(location, 0))
            prior_count = int(prior_moves.get(location, 0))
            difference = current_count - prior_count
            if difference > 0:
                comparison_text = f"{difference} more"
            elif difference < 0:
                comparison_text = f"{abs(difference)} fewer"
            else:
                comparison_text = "the same number of"
            location_insights.append({
                "Location": location,
                "Message": (
                    f"{comparison_text} students moved up in {title} than in "
                    f"{term} {year - 1} ({current_count} vs {prior_count})."
                ),
                "Projection": annual_move_projection(df, location)
            })

    instructor_data = instructor_records(
        df, latest["Start Date"].date(), latest["Swim End Date"].date(), shift_overrides
    )
    instructor_highlights = {}
    if not instructor_data.empty:
        instructor_data["Program Group"] = instructor_data["Level"].map(
            {
                level: group
                for group, levels in INSTRUCTOR_PROGRAM_GROUPS.items()
                for level in levels
            }
        )
        instructor_data = instructor_data.dropna(subset=["Program Group"])
        if not instructor_data.empty:
            # Count each child once per instructor and programme group, even
            # if they completed more than one level during the term.
            per_student = (
                instructor_data.groupby(
                    ["Program Group", "Instructor", "StudentID"], as_index=False
                )["Moved Up"].max()
            )
            instructor_stats = (
                per_student.groupby(["Program Group", "Instructor"], as_index=False)
                .agg(
                    Moved_Up=("Moved Up", "sum"),
                    Assessed=("StudentID", "nunique")
                )
            )
            instructor_stats["Move Up Rate"] = instructor_stats["Moved_Up"] / instructor_stats["Assessed"]

            for program_group in INSTRUCTOR_PROGRAM_GROUPS:
                eligible = instructor_stats[
                    (instructor_stats["Program Group"] == program_group) &
                    (instructor_stats["Assessed"] >= MIN_INSTRUCTOR_GROUP_STUDENTS)
                ]
                if eligible.empty:
                    instructor_highlights[program_group] = None
                    continue

                best_rate = eligible.sort_values(
                    ["Move Up Rate", "Assessed", "Instructor"],
                    ascending=[False, False, True]
                ).iloc[0]
                most_moves = eligible.sort_values(
                    ["Moved_Up", "Move Up Rate", "Instructor"],
                    ascending=[False, False, True]
                ).iloc[0]
                instructor_highlights[program_group] = {
                    "best_rate": best_rate,
                    "most_moves": most_moves
                }
    else:
        instructor_highlights = {group: None for group in INSTRUCTOR_PROGRAM_GROUPS}

    return title, {
        "locations": location_insights,
        "instructors": instructor_highlights
    }


@st.cache_data(show_spinner=False)
def annual_moveup_timeseries(df, location=None):
    """Calendar-aligned progression events with a March-to-date or prior-year pace forecast."""
    latest_booking = df["Start Date"].dropna().max()
    if pd.isna(latest_booking):
        return None

    as_of = pd.Timestamp(latest_booking).normalize()
    year = int(as_of.year)
    year_start = pd.Timestamp(year=year, month=1, day=1)
    year_end = pd.Timestamp(year=year, month=12, day=31)
    if as_of < year_start:
        return None
    as_of = min(as_of, year_end)

    source_df = df if location is None else df[df["Location"].eq(location)]
    # One event per student-level transition: use the final booking in the old
    # level, and require a next-level booking on or after that booking ends.
    completed = df.dropna(subset=["StudentID", "Level", "End Date"]).copy()
    completed["End Date"] = pd.to_datetime(completed["End Date"], errors="coerce")
    completed = completed.dropna(subset=["End Date"])
    final_dates = completed.groupby(["StudentID", "Level"])["End Date"].transform("max")
    final_bookings = completed[completed["End Date"].eq(final_dates)].copy()
    active_levels = set(zip(
        df.loc[df["End Date"].isna(), "StudentID"],
        df.loc[df["End Date"].isna(), "Level"]
    ))
    final_bookings = final_bookings[
        ~final_bookings.set_index(["StudentID", "Level"]).index.isin(active_levels)
    ]
    final_bookings = final_bookings.sort_values(["StudentID", "Level", "Location"]).drop_duplicates(
        ["StudentID", "Level"], keep="last"
    )
    next_bookings = df.dropna(subset=["StudentID", "Level", "Start Date"])
    next_starts = {
        key: group["Start Date"].tolist()
        for key, group in next_bookings.groupby(["StudentID", "Level"])
    }
    if not final_bookings.empty:
        final_bookings["Moved Up"] = final_bookings.apply(
            lambda row: _instructor_booking_moved_up(row, next_starts), axis=1
        )
        all_moves = final_bookings[final_bookings["Moved Up"]].copy()
    else:
        all_moves = final_bookings
    all_moves = all_moves.rename(columns={"End Date": "Move-Up Date"})
    all_moves["Move-Up Year"] = all_moves["Move-Up Date"].dt.year
    if location is not None:
        all_moves = all_moves[all_moves["Location"].eq(location)]

    actual_frames = []
    dated_years = pd.to_datetime(source_df["End Date"], errors="coerce").dropna().dt.year.tolist()
    available_years = sorted(set(dated_years) | {year})
    for chart_year in available_years:
        chart_start = pd.Timestamp(year=chart_year, month=1, day=1)
        year_moves = all_moves[all_moves["Move-Up Year"].eq(chart_year)]
        # Current year is cut off at the latest booking start. Earlier years
        # are shown through their last dated record, so incomplete coverage is
        # visible as a shorter line rather than a misleading flat tail.
        if chart_year == year:
            observed_through = as_of
        else:
            year_end_dates = pd.to_datetime(source_df.loc[pd.to_datetime(source_df["End Date"], errors="coerce").dt.year.eq(chart_year), "End Date"], errors="coerce")
            observed_through = year_end_dates.max()
        if pd.isna(observed_through):
            continue
        observed_through = min(pd.Timestamp(observed_through).normalize(), pd.Timestamp(year=chart_year, month=12, day=31))
        daily_index = pd.date_range(chart_start, observed_through, freq="D")
        year_moves = year_moves[year_moves["Move-Up Date"].le(observed_through)]
        daily_counts = year_moves.groupby(year_moves["Move-Up Date"].dt.normalize()).size()
        daily_cumulative = daily_counts.reindex(daily_index, fill_value=0).cumsum()
        weekly_actual = daily_cumulative.resample("W-SUN").last().dropna()
        frame = pd.DataFrame({"Year": str(chart_year), "Date": weekly_actual.index, "Cumulative Move-Ups": weekly_actual.values})
        if frame.empty or pd.Timestamp(frame.iloc[-1]["Date"]) != observed_through:
            frame = pd.concat([frame, pd.DataFrame({"Year": [str(chart_year)], "Date": [observed_through], "Cumulative Move-Ups": [int(daily_cumulative.iloc[-1])]})], ignore_index=True)
        display_year_end = pd.Timestamp(year=2000, month=12, day=31)
        frame["Plot Date"] = frame["Date"].map(
            lambda value: display_year_end if value.year > chart_year
            else pd.Timestamp(year=2000, month=value.month, day=value.day)
        )
        # A Sunday week-ending point can fall in January even though its count
        # is the completed prior year's total. Keep it at the December endpoint.
        actual_frames.append(frame.drop_duplicates("Plot Date", keep="last").sort_values("Plot Date"))

    actual_all = pd.concat(actual_frames, ignore_index=True) if actual_frames else pd.DataFrame(columns=["Year", "Date", "Plot Date", "Cumulative Move-Ups"])
    current_actual = actual_all[actual_all["Year"].eq(str(year))].copy()
    if current_actual.empty:
        return None
    daily_index = pd.date_range(year_start, as_of, freq="D")
    current_moves = all_moves[all_moves["Move-Up Year"].eq(year)]
    daily_counts = current_moves.groupby(current_moves["Move-Up Date"].dt.normalize()).size()
    daily_cumulative = daily_counts.reindex(daily_index, fill_value=0).cumsum()
    year_to_date = int(daily_cumulative.iloc[-1])
    year_totals = {}
    for chart_year in available_years:
        year_total_moves = all_moves[all_moves["Move-Up Year"].eq(chart_year)]
        if chart_year == year:
            year_total_moves = year_total_moves[year_total_moves["Move-Up Date"].le(as_of)]
        year_totals[str(chart_year)] = int(len(year_total_moves))
    march_first = pd.Timestamp(year=year, month=3, day=1)
    current_pace_days = (as_of - march_first).days + 1
    pace_year = year if current_pace_days >= 28 else year - 1
    pace_start = pd.Timestamp(year=pace_year, month=3, day=1)
    if pace_year == year:
        pace_end = as_of
    else:
        prior_dates = pd.to_datetime(source_df["End Date"], errors="coerce")
        prior_dates = prior_dates[prior_dates.dt.year.eq(pace_year)]
        pace_end = min(prior_dates.max(), pd.Timestamp(year=pace_year, month=12, day=31)) if not prior_dates.empty else pd.NaT

    pace_days = max(0, (pace_end - pace_start).days + 1) if pd.notna(pace_end) else 0
    pace_index = pd.date_range(pace_start, pace_end, freq="D") if pace_days else pd.DatetimeIndex([])
    pace_moves = all_moves[
        all_moves["Move-Up Year"].eq(pace_year) & all_moves["Move-Up Date"].between(pace_start, pace_end, inclusive="both")
    ] if pace_days else all_moves.iloc[0:0]
    pace_counts = pace_moves.groupby(pace_moves["Move-Up Date"].dt.normalize()).size()
    pace_daily = pace_counts.reindex(pace_index, fill_value=0).astype(float)
    weekly_average = float(pace_daily.sum() * 7 / pace_days) if pace_days else 0.0
    weekly_rates = [
        float(pace_daily.iloc[index:index + 7].sum() * 7 / len(pace_daily.iloc[index:index + 7]))
        for index in range(0, len(pace_daily), 7)
    ]
    weekly_std = float(pd.Series(weekly_rates).std(ddof=1)) if len(weekly_rates) > 1 else 0.0
    if weekly_average > 0:
        # A minimum Poisson-like spread keeps the band visible when weekly
        # counts happen to be identical in the observed weeks.
        weekly_std = max(weekly_std, weekly_average ** 0.5)

    forecast = pd.DataFrame(columns=["Date", "Plot Date", "Predicted", "Lower", "Upper"])
    if as_of < year_end and pace_days >= 28 and weekly_average > 0:
        point_dates = [as_of]
        cursor = as_of + pd.Timedelta(days=7)
        while cursor < year_end:
            point_dates.append(cursor)
            cursor += pd.Timedelta(days=7)
        if point_dates[-1] != year_end:
            point_dates.append(year_end)

        forecast_rows = [{
            "Date": as_of, "Predicted": float(year_to_date),
            "Lower": float(year_to_date), "Upper": float(year_to_date)
        }]
        for point in point_dates[1:]:
            horizon_weeks = (point - as_of).days / 7
            predicted = year_to_date + weekly_average * horizon_weeks
            uncertainty = 1.96 * weekly_std * (horizon_weeks ** 0.5)
            forecast_rows.append({
                "Date": point,
                "Predicted": predicted,
                "Lower": max(float(year_to_date), predicted - uncertainty),
                "Upper": predicted + uncertainty
            })
        forecast = pd.DataFrame(forecast_rows)
        forecast["Plot Date"] = forecast["Date"].map(lambda value: pd.Timestamp(year=2000, month=value.month, day=value.day))
        forecast["Year"] = str(year)

    projection = float(forecast.iloc[-1]["Predicted"]) if not forecast.empty else float(year_to_date)
    lower = float(forecast.iloc[-1]["Lower"]) if not forecast.empty else float(year_to_date)
    upper = float(forecast.iloc[-1]["Upper"]) if not forecast.empty else float(year_to_date)
    return {
        "year": year,
        "as_of": as_of,
        "forecast_start": pace_start,
        "pace_year": pace_year,
        "year_totals": year_totals,
        "actual": actual_all,
        "forecast": forecast,
        "year_to_date": year_to_date,
        "projection": projection,
        "lower": lower,
        "upper": upper,
        "has_forecast": not forecast.empty,
        "year_complete": as_of >= year_end
    }


def annual_moveup_chart(series):
    if series is None or series["actual"].empty:
        return None
    actual = alt.Chart(series["actual"]).mark_line(
        strokeWidth=2.5, point=alt.OverlayMarkDef(size=35)
    ).encode(
        x=alt.X("Plot Date:T", title="Month", axis=alt.Axis(format="%b", tickCount=12)),
        y=alt.Y("Cumulative Move-Ups:Q", title="Total move-ups", scale=alt.Scale(zero=True)),
        color=alt.Color("Year:N", title="Calendar year", scale=alt.Scale(scheme="tableau10")),
        tooltip=[
            alt.Tooltip("Year:N", title="Year"),
            alt.Tooltip("Date:T", title="Week ending", format="%d %b %Y"),
            alt.Tooltip("Cumulative Move-Ups:Q", title="Move-ups", format=",")
        ]
    )
    if not series["has_forecast"]:
        return actual.properties(height=300)

    forecast_data = series["forecast"]
    band = alt.Chart(forecast_data).mark_area(color="#D58A2A", opacity=0.17).encode(
        x=alt.X("Plot Date:T"),
        y=alt.Y("Lower:Q", title="Total move-ups", scale=alt.Scale(zero=True)),
        y2=alt.Y2("Upper:Q"),
        tooltip=[
            alt.Tooltip("Date:T", title="Forecast date", format="%d %b"),
            alt.Tooltip("Lower:Q", title="Low estimate", format=".0f"),
            alt.Tooltip("Predicted:Q", title="Expected", format=".0f"),
            alt.Tooltip("Upper:Q", title="High estimate", format=".0f")
        ]
    )
    predicted = alt.Chart(forecast_data).mark_line(
        strokeWidth=2.5, strokeDash=[7, 5]
    ).encode(
        x=alt.X("Plot Date:T"),
        y=alt.Y("Predicted:Q", title="Total move-ups", scale=alt.Scale(zero=True)),
        color=alt.Color("Year:N", title="Calendar year", scale=alt.Scale(scheme="tableau10")),
        tooltip=[
            alt.Tooltip("Date:T", title="Forecast date", format="%d %b"),
            alt.Tooltip("Predicted:Q", title="Expected move-ups", format=".0f")
        ]
    )
    return alt.layer(band, predicted, actual).resolve_scale(y="shared").properties(height=300)


# -------------------------
# UI (DEFAULT PAGE)
# -------------------------
# Choose a page before running its calculations; page interactions then skip home-only work.
if st.session_state.get("dashboard_page") == "Instructor Insights":
    st.session_state["dashboard_page"] = INSTRUCTOR_INSIGHTS_PAGE
elif st.session_state.get("dashboard_page") == "Shift Editor":
    st.session_state["dashboard_page"] = SHIFT_EDITOR_PAGE
elif st.session_state.get("dashboard_page") == "Group Analysis":
    st.session_state["dashboard_page"] = "Multi-Level Trends"

page = st.radio(
    "Dashboard page",
    ["Home", "Current Swimmers", "Level Trends", "Multi-Level Trends", "Student Lookup", "Yearly Export", INSTRUCTOR_INSIGHTS_PAGE, SHIFT_EDITOR_PAGE],
    horizontal=True,
    key="dashboard_page",
    label_visibility="collapsed"
)

shift_overrides = load_shift_overrides()
instructor_term = latest_completed_term(full_list, term_calendar)
insight_term = None
instructor_term_start = None
instructor_term_end = None
term_shift_rows = []
term_shift_staff_options = []
instructor_count = 0
if instructor_term is not None:
    instructor_term_start = instructor_term["Start Date"].date()
    instructor_term_end = instructor_term["Swim End Date"].date()
    insight_term = f"{instructor_term['Term']} {int(instructor_term['Year'])}"
    if page in {"Home", SHIFT_EDITOR_PAGE}:
        term_shift_rows, term_shift_staff_options = instructor_shift_editor_data(
            full_list, instructor_term_start, instructor_term_end, shift_overrides
        )
        instructor_names_in_term = set()
        for shift_row in term_shift_rows:
            name = shift_row["Assignment"]
            if name == "Use inferred":
                name = shift_row["Inferred Default"]
            if name not in {"Unknown", "Needs review"}:
                instructor_names_in_term.add(name)
        instructor_count = len(instructor_names_in_term)

if page == "Home":
    active_students_count = full_list.loc[full_list["End Date"].isna(), "StudentID"].nunique()
    student_count = full_list["StudentID"].nunique()

    metric_cols = st.columns(4)
    metric_cols[0].metric("Active Swimmers", f"{active_students_count:,}")
    metric_cols[1].metric("Students In Data", f"{student_count:,}")
    metric_cols[2].metric("Locations Loaded", f"{len(available_locations)}")
    metric_cols[3].metric("Instructors Listed · BETA", f"{instructor_count:,}")
    insight_term, insight_data = build_term_insights(full_list, term_calendar, shift_overrides)
    st.subheader("Insights")
    if insight_term:
        st.caption(f"Location comparison and instructor results: latest completed term, {insight_term}.")

    st.markdown("**Move-Ups By Main Location**")
    location_cols = st.columns(3)
    for index, location_insight in enumerate(insight_data["locations"]):
        with location_cols[index]:
            st.markdown(f"**{location_insight['Location']}**")
            st.write(location_insight["Message"])
            st.caption(location_insight["Projection"])

    st.markdown("**Yearly Move-Up Trend**")
    moveup_series = annual_moveup_timeseries(full_list)
    if moveup_series is None:
        st.info("Add booking data with dates to show the yearly move-up trend.")
    else:
        trend_metrics = st.columns(3)
        trend_metrics[0].metric(
            f"{moveup_series['year']} Move-Ups So Far",
            f"{moveup_series['year_to_date']:,}",
            help=f"Recorded through {moveup_series['as_of']:%d %b %Y}."
        )
        if moveup_series["has_forecast"]:
            trend_metrics[1].metric("Estimated Year-End Total", f"{moveup_series['projection']:.0f}")
            trend_metrics[2].metric(
                "Approximate Range",
                f"{moveup_series['lower']:.0f}–{moveup_series['upper']:.0f}",
                help="Approximate 95% range from observed weekly variation. It assumes the year-to-date weekly pace continues."
            )
            st.caption(f"Forecast pace uses {moveup_series['pace_year']} move-ups since 1 Mar. Data through {moveup_series['as_of']:%d %b %Y}.")
        elif moveup_series["year_complete"]:
            trend_metrics[1].metric("Year-End Total", f"{moveup_series['year_to_date']:,}")
            trend_metrics[2].metric("Approximate Range", "—")
            st.caption("Recorded move-ups through year-end.")
        else:
            trend_metrics[1].metric("Year-End Estimate", "Not enough data")
            trend_metrics[2].metric("Approximate Range", "—")
            st.caption(f"Recorded move-ups through {moveup_series['as_of']:%d %b %Y}.")
        trend_chart = annual_moveup_chart(moveup_series)
        if trend_chart is not None:
            st.altair_chart(trend_chart, width="stretch")

    with st.expander("Instructor Highlights By Programme · BETA", expanded=False):
        st.caption("Ranked by move-up rate and number of students moved up in the latest completed term.")
        program_groups = list(INSTRUCTOR_PROGRAM_GROUPS)
        for row_start in range(0, len(program_groups), 2):
            group_cols = st.columns(2)
            for col_index, program_group in enumerate(program_groups[row_start:row_start + 2]):
                with group_cols[col_index]:
                    st.markdown(f"**{program_group}**")
                    highlights = insight_data["instructors"].get(program_group)
                    if not highlights:
                        st.write(f"No instructor had more than {MIN_INSTRUCTOR_GROUP_STUDENTS - 1} assessed students in this programme during {insight_term or 'the last completed term'}.")
                        continue

                    best_rate = highlights["best_rate"]
                    most_moves = highlights["most_moves"]
                    st.write(
                        f"Best move-up rate: **{best_rate['Instructor']}** — "
                        f"{best_rate['Move Up Rate']:.0%} "
                        f"({int(best_rate['Moved_Up'])}/{int(best_rate['Assessed'])})."
                    )
                    st.write(
                        f"Most students moved up: **{most_moves['Instructor']}** — "
                        f"{int(most_moves['Moved_Up'])} of {int(most_moves['Assessed'])}."
                    )
    st.divider()

if page == "Current Swimmers":

    st.header("Current Swimmers")
    with st.container():
        display_mode = st.selectbox("Breakdown", ["By Gender", "Combined Totals"], key="t1")
    show_total_only = display_mode == "Combined Totals"

    col1, col2 = st.columns(2)
    with col1:
        level1 = st.selectbox("First Level", all_levels, index=0, key="current_level_1")
        st.dataframe(level_summary(full_list, level1, show_total_only), width="stretch", hide_index=True)

    with col2:
        level2 = st.selectbox("Second Level", all_levels, index=2, key="current_level_2")
        st.dataframe(level_summary(full_list, level2, show_total_only), width="stretch", hide_index=True)


if page == "Level Trends":
    st.header("Level Trends")
    with st.container():
        control_cols = st.columns([2, 1])
        mode = control_cols[0].radio("View", ["Compare Levels", "Compare Periods"], horizontal=True, key="time_analysis_mode", label_visibility="collapsed")
        display_mode = control_cols[1].selectbox("Breakdown", ["By Gender", "Combined Totals"], key="t2")
    show_total_only = display_mode == "Combined Totals"
    if mode == "Compare Levels":
        level1 = all_levels[0]
        level2 = all_levels[2]
        with st.container():
            date_range = st.date_input(
                "Date Range",
                value=(datetime(2020,1,1), datetime.now())
            )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range

            if start_date <= end_date:
                col1, col2 = st.columns(2)

                with col1:
                    level1 = st.selectbox("Level 1", all_levels, key="ts1")
                    if level1 != "None":
                        st.dataframe(
                            time_spent_summary(full_list, start_date, end_date, level1, show_total_only), width="stretch", hide_index=True)

                with col2:
                    level2 = st.selectbox("Level 2", all_levels, key="ts2")
                    if level2 != "None":
                        st.dataframe(
                            time_spent_summary(full_list, start_date, end_date, level2, show_total_only), width="stretch", hide_index=True)
            else:
                st.error("Start date must be before end date")
    elif mode == "Compare Periods":
        level = st.selectbox("Select Level", all_levels)
        col1, col2 = st.columns(2)

        with col1:
            date_range_1 = st.date_input(
                "Period 1",
                value=(datetime(2024,1,1), datetime(2024,12,31)),
                key="p1"
            )

            if isinstance(date_range_1, tuple) and len(date_range_1) == 2:
                start1, end1 = date_range_1

                st.caption(f"{start1} → {end1}")

                st.dataframe(
                    time_spent_summary(full_list, start1, end1, level, show_total_only),
                    hide_index=True,
                    width="stretch"
                )


        with col2:
            date_range_2 = st.date_input(
                "Period 2",
                value=(datetime(2025,1,1), datetime(2025,12,31)),
                key="p2"
            )

            if isinstance(date_range_2, tuple) and len(date_range_2) == 2:
                start2, end2 = date_range_2

                st.caption(f"{start2} → {end2}")

                st.dataframe(
                    time_spent_summary(full_list, start2, end2, level, show_total_only),
                    hide_index=True,
                    width="stretch"
                )

    st.divider()
    st.subheader("Annual Progression Overview")
    selected_location = st.selectbox(
        "Location",
        ["All locations"] + available_locations
    )
    def make_chart(df, title, metric="Time Spent"):
        y_title = "Weeks" if metric == "Time Spent" else "Students"
        return (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x=alt.X("Year:O", title="Year"),

                # 👇 THIS is what creates side-by-side bars
                xOffset=alt.XOffset("Gender:N"),

                y=alt.Y(
                "Value:Q",
                title=y_title
                ),

                color=alt.Color(
                    "Gender:N",
                    scale=alt.Scale(
                        domain=["Male", "Female", "Total"],
                        range=["#1f77b4", "#ff69b4", "#999999"]
                    ),
                    legend=None
                )
            )
            .properties(title=title)
        )
    df = full_list.copy()

    if selected_location != "All locations":
        df = df[df["Location"] == selected_location]
    if mode == "Compare Periods":
        # ---------------- TIME SPENT ----------------
        chart_time = yearly_summary(df, level, show_total_only, "Time Spent")
        st.altair_chart(make_chart(chart_time, "Average Time Spent in Level", "Time Spent"), width='stretch')

        # ---------------- STUDENTS ----------------
        chart_students = yearly_summary(df, level, show_total_only, "Students")
        st.altair_chart(make_chart(chart_students, "Number of Students Moved Up", "Students"), width='stretch')
    
    elif mode == "Compare Levels":
        col1, col2 = st.columns(2)

        for col, lvl in zip([col1, col2], [level1, level2]):

            with col:

                with st.expander(lvl, expanded=False):

                    # TIME SPENT
                    df_time = yearly_summary(df, lvl, show_total_only, "Time Spent")
                    st.altair_chart(make_chart(df_time, "Average Time Spent in Level", "Time Spent"), width='stretch')

                    # STUDENTS
                    df_students = yearly_summary(df, lvl, show_total_only, "Students")
                    st.altair_chart(make_chart(df_students, "Number of Students Moved Up", "Students"), width='stretch')


if page == "Multi-Level Trends":

    st.header("Multi-Level Trends")

    # -------------------------
    # INPUTS
    # -------------------------
    with st.container():
        group_cols = st.columns([1.2, 1])
        date_range = group_cols[0].date_input("Date range (optional)", value=())
        display_mode = group_cols[1].selectbox("Breakdown", ["By Gender", "Combined Totals"], key="t3")
        selected_levels = st.multiselect("Levels", options=all_levels, placeholder="All Levels")
    show_total_only = display_mode == "Combined Totals"

    # -------------------------
    # SAFE DATE HANDLING
    # -------------------------
    start_date = None
    end_date = None

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range

    # -------------------------
    # RUN ANALYSIS
    # -------------------------
    results_df = run_group_analysis(
        full_list,
        locations,
        genders,
        start_date,
        end_date,
        selected_levels,
        show_total_only
    )

    # -------------------------
    # OUTPUT
    # -------------------------
    st.subheader("Results")
    st.dataframe(results_df, width="stretch", hide_index=True)


if page == "Student Lookup":

    st.header("Student Lookup")
    st.caption("View a student’s level history or filter active students.")

    with st.container():
        mode = st.radio(
            "View",
            ["Student Profile", "At-Risk Students"],
            horizontal=True,
            label_visibility="collapsed"
        )

    # =====================================================
    # STUDENT SEARCH
    # =====================================================
    if mode == "Student Profile":
        student_options, student_labels = student_lookup_options(full_list)

        selected_student = st.selectbox(
            "Search Student",
            student_options["StudentID"].tolist(),
            format_func=lambda x: student_labels.get(x, x)
        )

        if selected_student:

            df_student = full_list[
                full_list["StudentID"] == selected_student
            ].copy()

            df_student["Current"] = (
                df_student["End Date"].isna()
            )

            df_student = df_student.sort_values(
                "Start Date"
            )

            active_levels = sorted(df_student.loc[df_student["End Date"].isna(), "Level"].dropna().unique())
            student_metrics = st.columns(3)
            student_metrics[0].metric("Current Levels", ", ".join(active_levels) if active_levels else "None")
            student_metrics[1].metric("Bookings In File", f"{len(df_student):,}")
            student_metrics[2].metric("Levels In History", f"{df_student['Level'].nunique():,}")

            history = []

            for level in df_student["Level"].dropna().unique():
                level_rows = df_student[df_student["Level"] == level].copy()
                is_current = level_rows["End Date"].isna().any()

                start = level_rows["Start Date"].min()
                completed_end = level_rows["End Date"].max()
                end_display = datetime.now() if is_current else completed_end

                # Sum every booking in this level. Do not use max(end)-min(start)
                # because separate bookings/classes are separate time contributions.
                weeks = ((pd.Timestamp(datetime.now()) - level_rows["Start Date"]).dt.days / 7).clip(lower=0).sum() if is_current else level_rows["Time Spent"].sum() / 7

                history.append({
                    "Level": level,
                    "Start": start.date() if pd.notna(start) else None,
                    "End": end_display.date() if pd.notna(end_display) else None,
                    "Weeks": round(weeks, 1),
                    "Status": "Current" if is_current else "Completed"
                })

            history_df = pd.DataFrame(history)

            diffs = []

            for _, row in history_df.iterrows():

                level = row["Level"]

                avg_df = yearly_summary(
                    full_list,
                    level,
                    True,
                    "Time Spent"
                )

                if len(avg_df) > 0:
                    avg = avg_df["Value"].mean()
                    diff = row["Weeks"] - avg
                else:
                    avg = np.nan
                    diff = np.nan

                diffs.append({
                    "Level": level,
                    "Student Weeks": row["Weeks"],
                    "Average Weeks": avg,
                    "Difference": diff
                })

            diff_df = pd.DataFrame(diffs)

            diff_df["Student Weeks"] = (
                diff_df["Student Weeks"].round(1)
            )

            diff_df["Average Weeks"] = (
                diff_df["Average Weeks"].round(1)
            )

            diff_df["Difference"] = (
                diff_df["Difference"].round(1)
            )

            def color_diff(val):

                if pd.isna(val):
                    return ""

                if val < 0:
                    strength = min(abs(val) / 10, 1)
                    g = int(150 + 105 * strength)
                    return f"color: rgb(0,{g},0); font-weight: bold;"

                strength = min(val / 10, 1)
                r = int(150 + 105 * strength)
                return f"color: rgb({r},0,0); font-weight: bold;"

            styled_df = diff_df.style.format({
                "Student Weeks": "{:.1f}",
                "Average Weeks": "{:.1f}",
                "Difference": "{:.1f}"
            }).map(
                color_diff,
                subset=["Difference"]
            )

            st.subheader("Level History")
            st.dataframe(
                history_df.round(1),
                width="stretch",
                hide_index=True
            )

            st.subheader("Performance vs Average")
            st.dataframe(
                styled_df,
                width="stretch"
            )

    # =====================================================
    # STUDENTS AT RISK
    # =====================================================
    else:

        col1, col2, col3 = st.columns(3)

        with col1:
            min_weeks = st.selectbox(
                "Minimum Time In Level",
                [10, 20, 30, 40, 52],
                index=1
            )

        with col2:
            level_filter = st.selectbox(
                "Level",
                ["All"] + all_levels
            )

        with col3:
            days = schedule_day_options(full_list)

            day_filter = st.selectbox(
                "Day",
                ["All"] + list(days)
            )

        risk_df = students_at_risk(
            full_list,
            min_weeks,
            level_filter,
            day_filter
        )

        # Pagination
        page_size = 50

        total_pages = max(
            1,
            int(np.ceil(len(risk_df) / page_size))
        )

        student_page = st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            value=min(1, total_pages),
            step=1
        )

        start_row = (student_page - 1) * page_size
        end_row = start_row + page_size

        display_df = risk_df.iloc[
            start_row:end_row
        ]

        if risk_df.empty:
            st.info("No active students match these filters.")
        else:
            st.caption(
                f"Showing {start_row + 1}–{min(end_row, len(risk_df))} of {len(risk_df)} students"
            )
            st.dataframe(display_df.round(1), width="stretch", hide_index=True)

if page == "Yearly Export":

    st.header("Yearly Data Export")
    st.caption("Download annual time-in-level and student progression tables for the uploaded locations.")

    if st.button("Prepare Export", type="primary"):

        export_tables = build_yearly_export_tables(full_list)

        csv_text = ""

        for table in export_tables:

            csv_text += f"Location,{table['Location']}\n"
            csv_text += f"Gender,{table['Gender']}\n\n"

            csv_text += "Average Time Spent (Weeks)\n"
            csv_text += table["Time"].to_csv(index=False)
            csv_text += "\n"

            csv_text += "Students Moved Up\n"
            csv_text += table["Students"].to_csv(index=False)
            csv_text += "\n\n\n"

        st.download_button(
            "Download CSV",
            csv_text,
            file_name="yearly_summary_export.csv",
            mime="text/csv"
        )

if page == INSTRUCTOR_INSIGHTS_PAGE:
    st.header("Instructor Insights · BETA")
    st.caption("Names use the final First Last pair in the Instructor field. Edit shift assignments to correct them.")

    if instructor_term is None:
        st.info("There is not enough dated booking data to identify a latest completed term.")
    else:
        start_date, end_date = instructor_term_start, instructor_term_end
        st.caption(f"{insight_term} · {start_date:%d %b %Y} – {end_date:%d %b %Y}")
        st.button(
            "Edit Instructor Assignments By Shift · BETA",
            key="open_shift_editor",
            on_click=open_shift_editor
        )

        instructor_rows = instructor_records(
            full_list, start_date, end_date, shift_overrides
        )
        instructors = sorted(instructor_rows["Instructor"].dropna().unique()) if not instructor_rows.empty else []

        if not instructors:
            st.warning("No instructor names were found in final bookings for this term.")
        else:
            instructor_cols = st.columns([1.2, 1])
            instructor = instructor_cols[0].selectbox("Instructor", instructors)
            result_grouping = instructor_cols[1].selectbox("Group Results", ["By Level", "By Location"])
            level_breakdown = result_grouping == "By Level"
            instructor_df = instructor_summary(
                full_list, instructor, start_date, end_date, level_breakdown,
                records=instructor_rows
            )

            if instructor_df.empty:
                st.info("No eligible completed level records were found for this instructor in the latest completed term.")
            else:
                moved_count = int(instructor_df["Kids Moved Up"].sum())
                total_count = int(instructor_df["Total Kids"].sum())
                move_rate = moved_count / total_count * 100 if total_count else 0
                metric_row = st.columns(3)
                metric_row[0].metric("Move-Ups", f"{moved_count:,}")
                metric_row[1].metric("Student-Level Records", f"{total_count:,}")
                metric_row[2].metric("Move-Up Rate", f"{move_rate:.1f}%")
                st.subheader("Results")
                st.dataframe(
                    style_instructor_table(instructor_df), width="stretch", hide_index=True,
                    column_config={
                        "Kids Moved Up": st.column_config.NumberColumn("Moved Up", width="small", help="Students who moved up after their final booking in this level ended during the latest completed term"),
                        "Total Kids": st.column_config.NumberColumn("Kids", width="small", help="Students whose final booking in this level ended during the latest completed term"),
                        "Time Spent Before Moving Up": st.column_config.NumberColumn("Weeks Before Move", width="small", help="Average weeks spent with this instructor before moving up"),
                        "Move Up Percentage": st.column_config.NumberColumn("Move Up %", width="small", help="Share of these students who moved up"),
                        "Time vs Location Avg": st.column_config.NumberColumn("Weeks vs Location", width="small", help="Difference from the location average, in weeks"),
                        "Move Up % vs Location Avg": st.column_config.NumberColumn("Move Up % vs Location", width="small", help="Percentage point difference from the location average"),
                        "Time vs All Teachers Avg": st.column_config.NumberColumn("Weeks vs All", width="small", help="Difference from the overall instructor average, in weeks"),
                        "Move Up % vs All Teachers Avg": st.column_config.NumberColumn("Move Up % vs All", width="small", help="Percentage point difference from the overall instructor average")
                    }
                )

            st.divider()
            st.subheader("Instructor Leaderboard")
            st.caption("Assessed: distinct students whose final booking ended this term after at least one week with the instructor. Moved up: assessed students who booked a next level. Move-up % = moved up ÷ assessed. Minimum: 11 assessed.")
            rank_by = st.selectbox(
                "Sort Leaderboard By", ["Total Kids Moved Up", "Move-Up Percentage"],
                key="instructor_leaderboard_sort"
            )
            leaderboard = instructor_leaderboard(instructor_rows)
            if leaderboard.empty:
                st.info("No instructors meet the minimum of 11 students assessed in this term.")
            else:
                sort_column = {
                    "Total Kids Moved Up": "Total Kids Moved Up",
                    "Move-Up Percentage": "Move Up Percentage"
                }[rank_by]
                leaderboard = leaderboard.sort_values(
                    [sort_column, "Move Up Percentage", "Instructor"],
                    ascending=[False, False, True]
                ).reset_index(drop=True)
                leaderboard.insert(0, "Rank", range(1, len(leaderboard) + 1))
                leaderboard = leaderboard.rename(columns={"Move Up Percentage": "Move-Up Percentage"})
                st.dataframe(
                    leaderboard.style.format({
                        "Total Kids Moved Up": "{:.0f}",
                        "Move-Up Percentage": "{:.1f}%",
                        "Students Assessed": "{:.0f}"
                    }), width="stretch", hide_index=True
                )

            st.subheader("Move-Up Rate Distribution By Location")
            st.caption("Instructor counts by 5-point move-up-rate range. Hover over a location to isolate it.")
            distribution = instructor_location_distribution(instructor_rows)
            distribution_chart = instructor_distribution_chart(distribution, available_locations)
            if distribution_chart is None:
                st.info("There isn't enough instructor data by location to display the distribution yet.")
            else:
                st.altair_chart(distribution_chart, width="stretch")

if page == SHIFT_EDITOR_PAGE:
    st.header("Instructor Assignments By Shift · BETA")
    if instructor_term is None:
        st.info("A completed term is needed before shifts can be edited.")
    else:
        st.caption(f"{insight_term} assignments by weekday. Changes stay in this browser session and update home insights and the leaderboard.")
        st.caption("Enrolled counts include bookings overlapping the term; leaderboard counts include final bookings ending in the term. Choose ‘Use inferred’ to remove a saved change.")
        shift_rows = term_shift_rows
        shift_staff_options = term_shift_staff_options
        if not shift_rows:
            st.info("No scheduled shifts overlap the latest completed term.")
        else:
            if not shift_staff_options:
                st.warning("No instructor names could be extracted for this term. Check the uploaded instructor fields.")
            day_tabs = st.tabs(_WEEKDAY_NAMES)
            for day_index, tab in enumerate(day_tabs):
                with tab:
                    day_rows = [r for r in shift_rows if r["Weekday"] == day_index]
                    day_rows.sort(key=lambda r: (r["Location"], r["Start"], r["Class"], r["Level"]))
                    if not day_rows:
                        st.info("No shifts found for this weekday in the latest completed term.")
                        continue
                    editor_key = f"shift_editor_v2_{insight_term.replace(' ', '_')}_{day_index}"
                    editor_data = pd.DataFrame([{
                        "Shift Key": r["Shift Key"],
                        "Location": r["Location"],
                        "Class": r["Class"],
                        "Level": r["Level"],
                        "Time": f"{r['Start']}–{r['End']}",
                        "Enrolled Students": r["Students"],
                        "Inferred Default": r["Inferred Default"],
                        "Assignment": r["Assignment"]
                    } for r in day_rows])
                    with st.form(key=f"{editor_key}_form"):
                        edited = st.data_editor(
                            editor_data,
                            key=editor_key,
                            hide_index=True,
                            num_rows="fixed",
                            width="stretch",
                            column_order=["Location", "Class", "Level", "Time", "Students", "Inferred Default", "Assignment"],
                            column_config={
                                "Shift Key": None,
                                "Location": st.column_config.TextColumn(disabled=True, width="small"),
                                "Class": st.column_config.TextColumn(disabled=True),
                                "Level": st.column_config.TextColumn(disabled=True, width="small"),
                                "Time": st.column_config.TextColumn(disabled=True, width="small"),
                            "Enrolled Students": st.column_config.NumberColumn(
                                "Enrolled",
                                disabled=True,
                                width="small",
                                help="Distinct students whose booking overlaps the reporting term; not all will qualify for the final-booking leaderboard."
                            ),
                                "Inferred Default": st.column_config.TextColumn(disabled=True),
                                "Assignment": st.column_config.SelectboxColumn(
                                    "Instructor for this shift",
                                    options=["Use inferred"] + shift_staff_options,
                                    required=True
                                )
                            }
                        )
                        submitted = st.form_submit_button(
                            "Save " + _WEEKDAY_NAMES[day_index] + " Assignments",
                            type="primary"
                        )
                    if submitted:
                        updated_overrides = dict(shift_overrides)
                        defaults = {r["Shift Key"]: r["Inferred Default"] for r in day_rows}
                        for _, edit_row in edited.iterrows():
                            key = edit_row["Shift Key"]
                            selected = edit_row["Assignment"]
                            inferred = defaults.get(key, "Needs review")
                            if selected == "Use inferred" or selected == inferred:
                                updated_overrides.pop(key, None)
                            else:
                                updated_overrides[key] = selected
                        save_shift_overrides(updated_overrides)
                        st.success("Shift assignments saved. The home insights and leaderboard now use these corrections.")
                        st.rerun()
