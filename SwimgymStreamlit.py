import streamlit as st
import altair as alt
import pandas as pd
import numpy as np
from datetime import datetime

st.set_page_config(layout="wide")

# -------------------------
# PROCESS DATA (CLEAN)
# -------------------------
@st.cache_data
def process_data(full_list):

    # Fix locations (ONLY for rows that came from Sites originally)
    if "Class/Camp/Appointment" in full_list.columns:
        mask_sites = full_list["Location"] == "Sites"

        text_col = full_list.loc[mask_sites, "Class/Camp/Appointment"].astype(str)

        full_list.loc[mask_sites & text_col.str.contains("PAP", na=False), "Location"] = "PAP"
        full_list.loc[mask_sites & text_col.str.contains("WAI", na=False), "Location"] = "WAI"
        full_list.loc[mask_sites & text_col.str.contains("OT", na=False), "Location"] = "OT"
        full_list.loc[mask_sites & text_col.str.contains("MBS", na=False), "Location"] = "MBS"

    # Dates
    full_list["Start Date"] = pd.to_datetime(full_list["Start/Drop Date"].str.slice(6,16), format='%d/%m/%Y')
    full_list["End Date"] = pd.to_datetime(full_list["Start/Drop Date"].str.slice(21,31), format='%d/%m/%Y', errors='coerce')

    full_list = full_list.drop(columns=["Start/Drop Date", "Class/Camp/Appointment"])

    # Time spent
    full_list["Time Spent"] = (full_list["End Date"] - full_list["Start Date"]).dt.days
    full_list["Time Spent"] = full_list["Time Spent"].fillna((datetime.now() - full_list["Start Date"]).dt.days)

    # Age
    full_list["Birthday"] = pd.to_datetime(full_list["Birthday"], errors='coerce')
    full_list["Age"] = ((datetime.now() - full_list["Birthday"]).dt.days) / 365

    # Passed logic
    passable_levels = {
    "Seahorse": ["Turtles"], "Seahorse Toddler": ["Turtles"],
    "Turtles": ["Octopus"], "Octopus": [],
    "Starfish": ["Shrimp"], "Shrimp": ["Otters"],
    "Otters": ["Penguins"], "Penguins": ["Sharks"],
    "Sharks": [],
    "New Swimmers": ["Moving and Stroking"],
    "Moving and Stroking": ["Breathers One"],
    "Breathers One": ["Breathers Two"],
    "Breathers Two": ["Improvers"],
    "Improvers": ["Seals"],
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

    bookings = full_list[["Student", "Level"]].drop_duplicates()

    rows = []

    for _, row in full_list[["Student", "Level"]].drop_duplicates().iterrows():
        student = row["Student"]
        level = row["Level"]

        next_levels = passable_levels.get(level, [])

        if not next_levels:
            continue

        for nxt in next_levels:
            rows.append((student, level, nxt))

    next_df = pd.DataFrame(rows, columns=["Student", "Level", "Next Level"])

    df_pass = pd.merge(
        next_df,
        bookings,
        left_on=["Student", "Next Level"],
        right_on=["Student", "Level"],
        how="left",
        indicator=True
    )

    passed_pairs = df_pass[df_pass["_merge"] == "both"][["Student", "Level_x"]]
    passed_pairs.columns = ["Student", "Level"]

    full_list["Passed"] = full_list.set_index(["Student", "Level"]).index.isin(
        passed_pairs.set_index(["Student", "Level"]).index
    )

    return full_list

st.title("Swimgym Dashboard")

st.write("### Upload Required CSV Files")

lep_file = st.file_uploader("Upload LEP CSV", type="csv")
howick_file = st.file_uploader("Upload Howick CSV", type="csv")
sites_file = st.file_uploader("Upload Sites CSV", type="csv")

dataframes = []

if lep_file is not None:
    lep = pd.read_csv(lep_file, usecols=["Student","Birthday","Gender","Level","Class/Camp/Appointment","Start/Drop Date","Schedule"])
    lep["Location"] = "LEP"
    dataframes.append(lep)

if howick_file is not None:
    howick = pd.read_csv(howick_file, usecols=["Student","Birthday","Gender","Level","Class/Camp/Appointment","Start/Drop Date","Schedule"])
    howick["Location"] = "Howick"
    dataframes.append(howick)

if sites_file is not None:
    sites = pd.read_csv(sites_file, usecols=["Student","Birthday","Gender","Level","Class/Camp/Appointment","Start/Drop Date","Schedule"])
    sites["Location"] = "Sites"
    dataframes.append(sites)

# 🚫 HARD STOP if no data
if not dataframes:
    st.warning("Please upload at least one CSV file to use the app.")
    st.stop()

# ✅ Build dataset
full_list = pd.concat(dataframes, ignore_index=True)
full_list = process_data(full_list)

genders = ["Male", "Female"]
locations = ["LEP","Howick","PAP","WAI","OT","MBS","Total"]

all_levels = ["Seahorse","Seahorse Toddler","Turtles","Octopus","Starfish","Shrimp","Otters","Penguins",
              "Sharks","New Swimmers","Moving and Stroking","Breathers One","Breathers Two","Improvers",
              "Howick Seals","Seals","Orcas","Marlins","Intro to Club","Dolphins","Fundamental Skills",
              "Junior Olympians","Development","Junior Performance","Youth Performance","Open Performance",
              "Open Development","Adult Level 1","Adult Level 2","Adult Level 3","Teen New Swimmer",
              "Teen Moving and Stroking","Teen Breathers","Teen Improvers"]

# -------------------------
# LEVEL SUMMARY FUNCTION
# -------------------------
def level_summary(df, level, total_only=False):
    df = df[pd.isna(df["End Date"])]
    df = df[df["Level"] == level]

    earliest = (
    df.groupby(["Student", "Level"])["Start Date"]
    .min()
    .reset_index()
    .rename(columns={"Start Date": "Earliest Start"})
)

    df = df.merge(earliest, on=["Student", "Level"], how="left")
    df["Time In Level"] = (datetime.now() - df["Earliest Start"]).dt.days / 7
    results = []

    for loc in locations:
        if total_only:
            temp = df.copy()
            if loc != "Total":
                temp = temp[temp["Location"] == loc]

            students = temp.drop_duplicates(subset=["Student"])
            count = len(students)

            if count > 0 and not np.isnan(students["Age"].mean()):
                avg_age = students["Age"].mean()
                years = int(avg_age)
                months = int((avg_age - years) * 12)
                age_str = f"{years}y {months}m"
                avg_time = round(students["Time In Level"].mean(), 1)
            else:
                age_str = "-"
                avg_time = "-"

            results.append({
                "Location": loc,
                "Students": count,
                "Avg Age": age_str,
                "Avg Weeks in Level": avg_time
            })

        else:
            for gender in genders:
                temp = df.copy()

                if loc != "Total":
                    temp = temp[temp["Location"] == loc]

                temp = temp[temp["Gender"] == gender]

                students = temp.drop_duplicates(subset=["Student"])
                count = len(students)

                if count > 0 and not np.isnan(students["Age"].mean()):
                    avg_age = students["Age"].mean()
                    years = int(avg_age)
                    months = int((avg_age - years) * 12)
                    age_str = f"{years}y {months}m"
                    avg_time = round(students["Time In Level"].mean(), 1)
                else:
                    age_str = "-"
                    avg_time = "-"

                results.append({
                    "Location": loc,
                    "Gender": gender,
                    "Students": count,
                    "Avg Age": age_str,
                    "Avg Weeks in Level": avg_time
                })

    return pd.DataFrame(results)


def time_spent_summary(df, start_date, end_date, level, total_only=False):
    df = df[df["Passed"] == True]

    df = df[(df["End Date"] >= pd.to_datetime(start_date)) & (df["End Date"] <= pd.to_datetime(end_date))]

    results = []

    for loc in locations:

        if total_only:
            temp = df.copy()

            if loc != "Total":
                temp = temp[temp["Location"] == loc]

            temp = temp[temp["Level"] == level]

            if len(temp) == 0:
                results.append({
                    "Location": loc,
                    "Avg Weeks": 0,
                    "Students": 0
                })
                continue

            time_spent = temp["Time Spent"].sum() / 7

            if loc == "Total":
                temp = temp.drop_duplicates(subset=["Student", "Location"])
            else:
                temp = temp.drop_duplicates(subset=["Student"])

            n = len(temp)
            avg = round(time_spent / n, 1) if n > 0 else 0

            results.append({
                "Location": loc,
                "Avg Weeks": avg,
                "Students": n
            })

        else:
            for gender in genders:
                temp = df.copy()

                if loc != "Total":
                    temp = temp[temp["Location"] == loc]

                temp = temp[(temp["Level"] == level) & (temp["Gender"] == gender)]

                if len(temp) == 0:
                    results.append({
                        "Location": loc,
                        "Gender": gender,
                        "Avg Weeks": 0,
                        "Students": 0
                    })
                    continue

                time_spent = temp["Time Spent"].sum() / 7

                if loc == "Total":
                    temp = temp.drop_duplicates(subset=["Student", "Location"])
                else:
                    temp = temp.drop_duplicates(subset=["Student"])

                n = len(temp)
                avg = round(time_spent / n, 1) if n > 0 else 0

                results.append({
                    "Location": loc,
                    "Gender": gender,
                    "Avg Weeks": avg,
                    "Students": n
                })

    return pd.DataFrame(results)


def yearly_summary(df, level, show_total_only, metric="Time Spent"):

    df = df[df["Passed"] == True].copy()
    df = df[df["Level"] == level]

    df = df.dropna(subset=["End Date"])
    df["Year"] = df["End Date"].dt.year

    results = []

    for year in sorted(df["Year"].unique()):

        year_df = df[df["Year"] == year].copy()

        # -------------------------
        # TOTAL MODE
        # -------------------------
        if show_total_only:

            if metric == "Time Spent":

                # 1 row per student per location
                temp = year_df.drop_duplicates(subset=["Student", "Location"])

                total_weeks = temp["Time Spent"].sum() / 7
                students = temp["Student"].nunique()

                value = total_weeks / students if students > 0 else 0

            else:

                temp = year_df.drop_duplicates(subset=["Student"])
                value = len(temp)

            results.append({
                "Year": int(year),
                "Gender": "Total",
                "Value": round(value, 2),
                "Students": students if metric == "Time Spent" else len(temp)
            })

        # -------------------------
        # GENDER MODE
        # -------------------------
        else:

            for gender in genders:

                temp = year_df[year_df["Gender"] == gender].copy()

                if len(temp) == 0:
                    results.append({
                        "Year": int(year),
                        "Gender": gender,
                        "Value": 0,
                        "Students": 0
                    })
                    continue

                if metric == "Time Spent":

                    temp = temp.drop_duplicates(subset=["Student", "Location"])

                    total_weeks = temp["Time Spent"].sum() / 7
                    students = temp["Student"].nunique()

                    value = total_weeks / students if students > 0 else 0

                else:

                    temp = temp.drop_duplicates(subset=["Student"])
                    value = len(temp)
                    students = len(temp)

                results.append({
                    "Year": int(year),
                    "Gender": gender,
                    "Value": round(value, 2),
                    "Students": students
                })

    return pd.DataFrame(results)


def run_group_analysis(df, locations, genders, start_date, end_date, selected_levels, total_only=False):
    df = df.copy()

    df = df[df["Passed"] == True]

    # -------------------------
    # DATE FILTER
    # -------------------------
    if start_date is not None and end_date is not None:
        df = df[
            (df["End Date"] >= pd.to_datetime(start_date)) &
            (df["End Date"] <= pd.to_datetime(end_date))
        ]

    # -------------------------
    # LEVEL FILTER
    # -------------------------
    if selected_levels:
        df = df[df["Level"].isin(selected_levels)]

    # -------------------------
    # ANALYSIS
    # -------------------------
    results = []

    for location in locations:

        if total_only:
            temp = df.copy()

            if location != "Total":
                temp = temp[temp["Location"] == location]

            time_spent = temp["Time Spent"].sum()

            if time_spent > 0:
                time_spent /= 7

                if location == "Total":
                    temp = temp.drop_duplicates(subset=["Student", "Location"])
                else:
                    temp = temp.drop_duplicates(subset=["Student"])

                n = len(temp)
                avg = time_spent / n if n > 0 else 0

                results.append([
                    location,
                    round(avg, 1),
                    n
                ])

        else:
            for gender in genders:
                temp = df.copy()

                if location != "Total":
                    temp = temp[temp["Location"] == location]

                temp = temp[temp["Gender"] == gender]

                time_spent = temp["Time Spent"].sum()

                if time_spent > 0:
                    time_spent /= 7

                    if location == "Total":
                        temp = temp.drop_duplicates(subset=["Student", "Location"])
                    else:
                        temp = temp.drop_duplicates(subset=["Student"])

                    n = len(temp)
                    avg = time_spent / n if n > 0 else 0

                    results.append([
                        location,
                        gender,
                        round(avg, 1),
                        n
                    ])

    if total_only:
        return pd.DataFrame(results, columns=["Location", "Avg Weeks", "Students"])
    else:
        return pd.DataFrame(results, columns=["Location", "Gender", "Avg Weeks", "Students"])
# -------------------------
# UI (DEFAULT PAGE)
# -------------------------
tab1, tab2, tab3, tab4 = st.tabs([
    "Current Level Information",
    "Time Spent Analysis",
    "Time Spent Group Analysis",
    "Student Search"
])

with tab1:

    st.title("Current Level Information")
    show_total_only = st.toggle("Show totals only (combine genders, note some students may not have genders listed)", key="t1")

    col1, col2 = st.columns(2)
    with col1:
        level1 = st.selectbox("Level 1", all_levels)
        st.subheader(f"{level1}")
        st.dataframe(level_summary(full_list, level1, show_total_only), width="stretch", hide_index=True)

    with col2:
        level2 = st.selectbox("Level 2", all_levels)
        st.subheader(f"{level2}")
        st.dataframe(level_summary(full_list, level2, show_total_only), width="stretch", hide_index=True)


with tab2:
    st.title("Time Spent Analysis")
    mode = st.radio(
    "Analysis Mode",
    ["Compare Levels (same time)", "Compare Time Periods (same level)"])
    show_total_only = st.toggle("Show totals only (combine genders, note some students may not have genders listed)", key="t2")
    if mode == "Compare Levels (same time)":
        colA, colB, colC = st.columns([2,1,1])
        with colA:
            date_range = st.date_input(
                "Date Range",
                value=(datetime(2020,1,1), datetime.now())
            )
        with colB:
            level1 = st.selectbox("Level 1", all_levels, key="ts1")
        with colC:
            level2 = st.selectbox("Level 2", all_levels, key="ts2")
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range

            if start_date <= end_date:
                col1, col2 = st.columns(2)

                if level1 != "None":
                    with col1:
                        st.subheader(level1)
                        st.dataframe(
                            time_spent_summary(full_list, start_date, end_date, level1, show_total_only), width="stretch", hide_index=True)

                if level2 != "None":
                    with col2:
                        st.subheader(level2)
                        st.dataframe(
                            time_spent_summary(full_list, start_date, end_date, level2, show_total_only), width="stretch", hide_index=True)
            else:
                st.error("Start date must be before end date")
    elif mode == "Compare Time Periods (same level)":
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
    st.subheader("Yearly Performance Overview")
    selected_location = st.selectbox(
    "Select Location",
    ["All"] + locations
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

    if selected_location != "All":
        df = df[df["Location"] == selected_location]
    if mode == "Compare Time Periods (same level)":
        # ---------------- TIME SPENT ----------------
        chart_time = yearly_summary(df, level, show_total_only, "Time Spent")
        st.altair_chart(make_chart(chart_time, f"{level} - Average Time Spent in Level", "Time Spent"), width='stretch')

        # ---------------- STUDENTS ----------------
        chart_students = yearly_summary(df, level, show_total_only, "Students")
        st.altair_chart(make_chart(chart_students, f"{level} - Number of Students Moved Up", "Students"), width='stretch')
    
    elif mode == "Compare Levels (same time)":
        col1, col2 = st.columns(2)

        for col, lvl in zip([col1, col2], [level1, level2]):

            with col:

                st.subheader(lvl)

                # TIME SPENT
                df_time = yearly_summary(df, lvl, show_total_only, "Time Spent")
                st.altair_chart(make_chart(df_time, "Average Time Spent in Level", "Time Spent"), width='stretch')

                # STUDENTS
                df_students = yearly_summary(df, lvl, show_total_only, "Students")
                st.altair_chart(make_chart(df_students, "Number of Students Moved Up", "Students"), width='stretch')


with tab3:

    st.title("Group Analysis")

    # -------------------------
    # INPUTS
    # -------------------------
    date_range = st.date_input(
        "Select Date Range",
        value=()
    )

    selected_levels = st.multiselect(
        "Select Levels",
        options=all_levels
    )

    show_total_only = st.toggle("Show totals only (combine genders, note some students may not have genders listed)", key="t3")

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
    st.divider()

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
    st.dataframe(results_df, width="stretch", hide_index=True)


with tab4:

    st.title("Student Search")

    # -------------------------
    # SEARCH BOX
    # -------------------------
    student_list = sorted(full_list["Student"].dropna().unique())

    selected_student = st.selectbox(
        "Search Student",
        student_list
    )

    if selected_student:

        df_student = full_list[full_list["Student"] == selected_student].copy()
        df_student["Current"] = df_student["End Date"].isna()

        df_student = df_student.sort_values("Start Date")

        # -------------------------
        # BUILD LEVEL HISTORY
        # -------------------------
        history = []

        for level in df_student["Level"].unique():

            temp = df_student[df_student["Level"] == level]

            start = temp["Start Date"].min()
            end = temp["End Date"].max()

            is_current = temp["End Date"].isna().any()

            # If still in level
            if is_current:
                end_display = datetime.now()
            else:
                end_display = end

            weeks = (end_display - start).days / 7

            history.append({
                "Level": level,
                "Start": start.date(),
                "End": end_display.date(),
                "Weeks": round(weeks, 1),
                "Status": "Current" if is_current else "Completed"
            })

        history_df = pd.DataFrame(history)

        # -------------------------
        # COMPARE TO AVERAGE
        # -------------------------
        diffs = []

        for _, row in history_df.iterrows():

            level = row["Level"]

            if level == "Dolphins":
                avg = np.nan
                diff = np.nan
            else:
                avg_df = yearly_summary(full_list, level, True, "Time Spent")

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

        diff_df["Student Weeks"] = diff_df["Student Weeks"].round(1)
        diff_df["Average Weeks"] = diff_df["Average Weeks"].round(1)
        diff_df["Difference"] = diff_df["Difference"].round(1)

        # -------------------------
        # COLOR FUNCTION
        # -------------------------
        def color_diff(val):
            if pd.isna(val):
                return ""

            # Negative = faster = GOOD → green
            if val < 0:
                strength = min(abs(val) / 10, 1)  # scale intensity
                g = int(150 + 105 * strength)
                return f"color: rgb(0,{g},0); font-weight: bold;"

            # Positive = slower = BAD → red
            else:
                strength = min(val / 10, 1)
                r = int(150 + 105 * strength)
                return f"color: rgb({r},0,0); font-weight: bold;"

        # -------------------------
        # STYLE ONLY DIFFERENCE
        # -------------------------
        styled_df = diff_df.style.map(
            color_diff,
            subset=["Difference"]
        ).format({
            "Student Weeks": "{:.1f}",
            "Average Weeks": "{:.1f}",
            "Difference": "{:.1f}"
        })

        # -------------------------
        # OUTPUT
        # -------------------------
        st.subheader("Level History")
        st.dataframe(history_df, width="stretch", hide_index=True)

        st.subheader("Performance vs Average")
        st.dataframe(
            styled_df,
            width="stretch"
        )
