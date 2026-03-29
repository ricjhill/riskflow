"""RiskFlow Dashboard — 3-tab Streamlit GUI.

Tab 1: Mapping & Ingestion (for underwriters/brokers)
Tab 2: Harness Debugger (for DevOps/engineering)
Tab 3: Feedback & Corrections (for data quality)

Talks to the RiskFlow API via HTTP — never imports domain code.

Run with: uv run streamlit run gui/app.py
Requires: RiskFlow API running on localhost:8000
"""

import time

import httpx
import pandas as pd
import streamlit as st
import yaml

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gui.api_client import RiskFlowClient

import os

_default_api_url = os.environ.get("RISKFLOW_API_URL", "http://localhost:8000")
API_URL = st.sidebar.text_input("API URL", value=_default_api_url)
client = RiskFlowClient(base_url=API_URL)

st.title("RiskFlow Dashboard")

# --- Check API health ---
try:
    client.health()
    st.sidebar.success("API connected")
except httpx.ConnectError:
    st.sidebar.error("API not reachable. Start with: docker compose up -d")
    st.stop()
except Exception as e:
    st.sidebar.error(f"API error: {e}")
    st.stop()

# --- Load available schemas ---
try:
    schemas = client.list_schemas()
except Exception:
    schemas = []

# === TABS ===
tab1, tab2, tab3 = st.tabs(
    ["Mapping & Ingestion", "Harness Debugger", "Feedback & Corrections"]
)


# ── TAB 1: Mapping & Ingestion ──────────────────────────────────────────
with tab1:
    st.header("Upload & Map Bordereaux")

    # Sidebar config
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_schema = st.selectbox(
            "Target Schema", schemas, index=0 if schemas else None
        )
    with col2:
        confidence_threshold = st.slider("Confidence Threshold", 0.0, 1.0, 0.6, 0.05)

    uploaded_file = st.file_uploader(
        "Upload Bordereaux", type=["csv", "xlsx", "xls"], key="tab1_upload"
    )

    cedent_id = st.text_input(
        "Cedent ID (optional)", placeholder="e.g. ACME-RE", key="tab1_cedent"
    )

    if uploaded_file:
        file_bytes = uploaded_file.getvalue()
        filename = uploaded_file.name

        # Sheet selection for Excel
        sheet_name = None
        if filename.endswith((".xlsx", ".xls")):
            try:
                sheets = client.list_sheets(file_bytes, filename)
                if sheets:
                    sheet_name = st.selectbox("Select Sheet", sheets)
            except Exception:
                pass

        # Raw preview
        st.subheader("Raw Input (first 5 rows)")
        try:
            if filename.endswith(".csv"):
                preview_df = pd.read_csv(uploaded_file, nrows=5)
            else:
                preview_df = pd.read_excel(
                    uploaded_file, nrows=5, sheet_name=sheet_name
                )
            st.dataframe(preview_df, use_container_width=True)
            uploaded_file.seek(0)
        except Exception as e:
            st.warning(f"Could not preview: {e}")

        # Map button
        if st.button("Map & Validate", type="primary"):
            start = time.monotonic()
            try:
                result = client.upload(
                    file_bytes,
                    filename,
                    schema=selected_schema,
                    sheet_name=sheet_name,
                    cedent_id=cedent_id if cedent_id.strip() else None,
                )
                elapsed_ms = int((time.monotonic() - start) * 1000)

                # Mapping results
                st.subheader("Column Mappings")
                mappings = result["mapping"]["mappings"]
                unmapped = result["mapping"]["unmapped_headers"]

                mapping_data = []
                for m in mappings:
                    conf = m["confidence"]
                    status = "High" if conf >= confidence_threshold else "Low"
                    mapping_data.append(
                        {
                            "Source Header": m["source_header"],
                            "Target Field": m["target_field"],
                            "Confidence": f"{conf:.0%}",
                            "Status": status,
                        }
                    )
                if unmapped:
                    for h in unmapped:
                        mapping_data.append(
                            {
                                "Source Header": h,
                                "Target Field": "(unmapped)",
                                "Confidence": "—",
                                "Status": "Unmapped",
                            }
                        )

                mapping_df = pd.DataFrame(mapping_data)
                st.dataframe(
                    mapping_df.style.apply(
                        lambda row: (
                            [
                                "background-color: #d4edda"
                                if row["Status"] == "High"
                                else "background-color: #f8d7da"
                                if row["Status"] in ("Low", "Unmapped")
                                else ""
                            ]
                            * len(row)
                        ),
                        axis=1,
                    ),
                    use_container_width=True,
                )

                # Confidence report
                cr = result["confidence_report"]
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Min Confidence", f"{cr['min_confidence']:.0%}")
                col_b.metric("Avg Confidence", f"{cr['avg_confidence']:.0%}")
                col_c.metric("Processing Time", f"{elapsed_ms} ms")

                if cr["missing_fields"]:
                    st.warning(f"Missing fields: {', '.join(cr['missing_fields'])}")
                if cr["low_confidence_fields"]:
                    low_names = [f["target_field"] for f in cr["low_confidence_fields"]]
                    st.warning(f"Low confidence: {', '.join(low_names)}")

                # Valid records
                valid = result["valid_records"]
                invalid = result["invalid_records"]
                errors = result["errors"]

                st.subheader(f"Valid Records ({len(valid)})")
                if valid:
                    st.dataframe(pd.DataFrame(valid), use_container_width=True)

                    # Download button
                    csv_data = pd.DataFrame(valid).to_csv(index=False)
                    st.download_button(
                        "Download Clean CSV",
                        csv_data,
                        file_name=f"mapped_{filename.rsplit('.', 1)[0]}.csv",
                        mime="text/csv",
                    )

                if errors:
                    st.subheader(f"Validation Errors ({len(errors)})")
                    for err in errors:
                        st.error(f"Row {err['row']}: {err['error']}")

            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", {})
                    if isinstance(detail, dict):
                        st.error(
                            f"**{detail.get('error_code', 'ERROR')}:** "
                            f"{detail.get('message', str(e))}"
                        )
                        if detail.get("suggestion"):
                            st.info(detail["suggestion"])
                    else:
                        st.error(f"Error: {detail}")
                except Exception:
                    st.error(f"API error: {e.response.status_code} — {e.response.text}")
            except Exception as e:
                st.error(f"Error: {e}")


# ── TAB 2: Harness Debugger ─────────────────────────────────────────────
with tab2:
    st.header("Harness Debugger")

    debug_schema = st.selectbox("Schema to inspect", schemas, key="debug_schema")

    if debug_schema:
        # Load and display schema YAML
        schema_path = f"schemas/{debug_schema}.yaml"
        try:
            with open(schema_path) as f:
                schema_data = yaml.safe_load(f)

            col_left, col_right = st.columns(2)

            with col_left:
                st.subheader("Schema Definition")
                st.code(
                    yaml.dump(schema_data, default_flow_style=False), language="yaml"
                )

            with col_right:
                st.subheader("Schema Properties")
                fields = schema_data.get("fields", {})
                st.metric("Fields", len(fields))
                st.metric(
                    "Required",
                    sum(1 for f in fields.values() if f.get("required", True)),
                )
                st.metric(
                    "Optional",
                    sum(1 for f in fields.values() if not f.get("required", True)),
                )
                st.metric(
                    "Cross-field Rules", len(schema_data.get("cross_field_rules", []))
                )
                st.metric("SLM Hints", len(schema_data.get("slm_hints", [])))

            # Reconstruct the prompt (same logic as _build_system_prompt)
            st.subheader("SLM Prompt (what the AI sees)")
            field_names = sorted(fields.keys())
            fields_str = ", ".join(field_names)

            prompt = (
                "You are a reinsurance data specialist. Map spreadsheet column headers "
                "to the standard schema.\n\n"
                f"Target schema fields: {fields_str}.\n"
            )

            hints = schema_data.get("slm_hints", [])
            if hints:
                prompt += "\nKnown aliases:\n"
                for hint in hints:
                    prompt += (
                        f'- "{hint["source_alias"]}" typically means {hint["target"]}\n'
                    )
            else:
                prompt += "\nNo known aliases for this schema.\n"

            prompt += (
                "\nRespond ONLY with valid JSON matching this structure:\n"
                '{"mappings": [{"source_header": "...", "target_field": "...", "confidence": 0.95}], '
                '"unmapped_headers": ["..."]}\n\n'
                "Rules:\n"
                f"- target_field MUST be one of: {fields_str}\n"
                "- confidence is a float between 0.0 and 1.0\n"
                "- Headers that don't map to any target field go in unmapped_headers"
            )

            st.code(prompt, language="text")

            # Field details table
            st.subheader("Field Definitions")
            field_rows = []
            for name, defn in fields.items():
                constraints = []
                if defn.get("not_empty"):
                    constraints.append("not empty")
                if defn.get("non_negative"):
                    constraints.append("non-negative")
                if defn.get("allowed_values"):
                    constraints.append(f"one of: {defn['allowed_values']}")
                field_rows.append(
                    {
                        "Field": name,
                        "Type": defn["type"],
                        "Required": defn.get("required", True),
                        "Constraints": ", ".join(constraints) if constraints else "—",
                    }
                )
            st.dataframe(pd.DataFrame(field_rows), use_container_width=True)

        except FileNotFoundError:
            st.warning(
                f"Schema file not found at {schema_path}. "
                "The GUI reads YAML files directly from the schemas/ directory."
            )


# ── TAB 3: Feedback & Corrections ───────────────────────────────────────
with tab3:
    st.header("Mapping Corrections")

    st.markdown(
        "Submit corrections when the AI maps a header incorrectly. "
        "Corrections are stored per cedent — future uploads from the same cedent "
        "apply corrections automatically with 100% confidence."
    )

    corr_cedent = st.text_input(
        "Cedent ID", placeholder="e.g. ACME-RE", key="corr_cedent"
    )

    # Get target fields from the selected schema
    corr_schema = st.selectbox(
        "Schema (for valid target fields)", schemas, key="corr_schema"
    )
    target_fields = []
    if corr_schema:
        try:
            with open(f"schemas/{corr_schema}.yaml") as f:
                schema_data = yaml.safe_load(f)
                target_fields = sorted(schema_data.get("fields", {}).keys())
        except FileNotFoundError:
            pass

    st.subheader("Add Corrections")

    # Dynamic correction rows
    if "corrections" not in st.session_state:
        st.session_state.corrections = [{"source_header": "", "target_field": ""}]

    corrections_to_submit = []
    for i, corr in enumerate(st.session_state.corrections):
        col_src, col_tgt, col_del = st.columns([3, 3, 1])
        with col_src:
            source = st.text_input(
                "Source Header",
                value=corr["source_header"],
                key=f"src_{i}",
                placeholder="e.g. TSI",
            )
        with col_tgt:
            target = st.selectbox(
                "Target Field",
                [""] + target_fields,
                key=f"tgt_{i}",
            )
        with col_del:
            if st.button("X", key=f"del_{i}"):
                st.session_state.corrections.pop(i)
                st.rerun()

        if source.strip() and target:
            corrections_to_submit.append(
                {"source_header": source.strip(), "target_field": target}
            )

    if st.button("+ Add Row"):
        st.session_state.corrections.append({"source_header": "", "target_field": ""})
        st.rerun()

    # Submit
    if st.button("Save Corrections to Redis", type="primary"):
        if not corr_cedent.strip():
            st.error("Cedent ID is required")
        elif not corrections_to_submit:
            st.error("Add at least one correction")
        else:
            try:
                count = client.submit_corrections(
                    corr_cedent.strip(), corrections_to_submit
                )
                st.success(f"Stored {count} correction(s) for cedent '{corr_cedent}'")
                st.session_state.corrections = [
                    {"source_header": "", "target_field": ""}
                ]
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", {})
                    if isinstance(detail, dict):
                        st.error(detail.get("message", str(e)))
                    else:
                        st.error(str(detail))
                except Exception:
                    st.error(f"Error: {e}")

    st.divider()
    st.markdown(
        "**How corrections work:** Once saved, uploading with "
        "`?cedent_id=ACME-RE` will apply these corrections before calling the AI. "
        "Corrected headers get confidence 1.0 — the AI is skipped for those headers."
    )
