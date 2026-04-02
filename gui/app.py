"""RiskFlow Dashboard — 4-tab Streamlit GUI.

Tab 1: Mapping & Ingestion (for underwriters/brokers)
Tab 2: Harness Debugger (for DevOps/engineering)
Tab 3: Feedback & Corrections (for data quality)
Tab 4: Flow Mapper (interactive session-based mapping)

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
tab1, tab2, tab3, tab4 = st.tabs(
    ["Mapping & Ingestion", "Harness Debugger", "Feedback & Corrections", "Flow Mapper"]
)


# ── TAB 1: Mapping & Ingestion ──────────────────────────────────────────
with tab1:
    st.header("Upload & Map Bordereaux")

    # Sidebar config
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_schema = st.selectbox("Target Schema", schemas, index=0 if schemas else None)
    with col2:
        confidence_threshold = st.slider("Confidence Threshold", 0.0, 1.0, 0.6, 0.05)

    uploaded_file = st.file_uploader(
        "Upload Bordereaux", type=["csv", "xlsx", "xls"], key="tab1_upload"
    )

    cedent_id = st.text_input("Cedent ID (optional)", placeholder="e.g. ACME-RE", key="tab1_cedent")

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
                preview_df = pd.read_excel(uploaded_file, nrows=5, sheet_name=sheet_name)
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
                st.code(yaml.dump(schema_data, default_flow_style=False), language="yaml")

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
                st.metric("Cross-field Rules", len(schema_data.get("cross_field_rules", [])))
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
                    prompt += f'- "{hint["source_alias"]}" typically means {hint["target"]}\n'
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

    corr_cedent = st.text_input("Cedent ID", placeholder="e.g. ACME-RE", key="corr_cedent")

    # Get target fields from the selected schema
    corr_schema = st.selectbox("Schema (for valid target fields)", schemas, key="corr_schema")
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
            corrections_to_submit.append({"source_header": source.strip(), "target_field": target})

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
                count = client.submit_corrections(corr_cedent.strip(), corrections_to_submit)
                st.success(f"Stored {count} correction(s) for cedent '{corr_cedent}'")
                st.session_state.corrections = [{"source_header": "", "target_field": ""}]
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


# ── TAB 4: Flow Mapper ────────────────────────────────────────────────
# Interactive mapping: upload → review SLM suggestions → edit → finalise


def _mapping_editor(
    source_headers: list[str],
    target_fields: list[str],
    current_mappings: list[dict],
) -> tuple[list[dict], list[str]]:
    """Render mapping editor with selectboxes. Returns (mappings, unmapped).

    This is the Option 2 swap point — replace the body with a
    Streamlit custom component (React drag-and-drop) when ready.
    """
    UNMAPPED = "-- unmapped --"
    options = [UNMAPPED] + sorted(target_fields)

    # Build lookup: source_header → current target_field
    current_map = {m["source_header"]: m["target_field"] for m in current_mappings}
    confidence_map = {m["source_header"]: m["confidence"] for m in current_mappings}

    updated_mappings = []
    updated_unmapped = []

    # Header row
    col_hdr_src, col_hdr_tgt, col_hdr_conf = st.columns([3, 3, 1])
    col_hdr_src.markdown("**Source Header**")
    col_hdr_tgt.markdown("**Target Field**")
    col_hdr_conf.markdown("**Conf.**")

    for header in source_headers:
        col_src, col_tgt, col_conf = st.columns([3, 3, 1])

        with col_src:
            st.text(header)

        current_target = current_map.get(header, UNMAPPED)
        default_idx = options.index(current_target) if current_target in options else 0

        with col_tgt:
            selected = st.selectbox(
                f"Target for {header}",
                options,
                index=default_idx,
                key=f"flow_map_{header}",
                label_visibility="collapsed",
            )

        with col_conf:
            conf = confidence_map.get(header)
            if conf is not None:
                st.text(f"{conf:.0%}")
            else:
                st.text("--")

        if selected == UNMAPPED:
            updated_unmapped.append(header)
        else:
            updated_mappings.append(
                {
                    "source_header": header,
                    "target_field": selected,
                    "confidence": confidence_map.get(header, 1.0),
                }
            )

    return updated_mappings, updated_unmapped


def _show_api_error(e: httpx.HTTPStatusError) -> None:
    """Display a structured API error."""
    try:
        detail = e.response.json().get("detail", {})
        if isinstance(detail, dict):
            st.error(f"**{detail.get('error_code', 'ERROR')}:** {detail.get('message', str(e))}")
            if detail.get("suggestion"):
                st.info(detail["suggestion"])
        else:
            st.error(f"Error: {detail}")
    except Exception:
        st.error(f"API error: {e.response.status_code} — {e.response.text}")


def _reset_flow_session() -> None:
    """Clean up the current session and reset state."""
    sid = st.session_state.get("flow_session_id")
    if sid:
        try:
            client.delete_session(sid)
        except Exception:
            pass
    st.session_state.flow_session_id = None
    st.session_state.flow_session_data = None
    st.session_state.flow_step = "upload"
    st.session_state.flow_custom_field_types = {}


with tab4:
    st.header("Flow Mapper")
    st.caption("Interactive mapping: upload, review AI suggestions, edit, finalise.")

    # Initialize session state
    if "flow_step" not in st.session_state:
        st.session_state.flow_step = "upload"
    if "flow_session_id" not in st.session_state:
        st.session_state.flow_session_id = None
    if "flow_session_data" not in st.session_state:
        st.session_state.flow_session_data = None

    # Step indicator
    steps = ["Upload", "Review & Edit", "Results"]
    step_idx = {"upload": 0, "review": 1, "results": 2}
    current = step_idx.get(st.session_state.flow_step, 0)
    cols = st.columns(len(steps))
    for i, (col, label) in enumerate(zip(cols, steps, strict=True)):
        if i < current:
            col.success(f"**{i + 1}. {label}**")
        elif i == current:
            col.info(f"**{i + 1}. {label}**")
        else:
            col.markdown(f"{i + 1}. {label}")

    st.divider()

    # ── Step 1: Upload ──
    if st.session_state.flow_step == "upload":
        flow_col1, flow_col2 = st.columns([2, 1])
        with flow_col1:
            flow_schema = st.selectbox(
                "Target Schema", schemas, index=0 if schemas else None, key="flow_schema"
            )
        with flow_col2:
            st.markdown("")  # spacer

        flow_file = st.file_uploader(
            "Upload Bordereaux", type=["csv", "xlsx", "xls"], key="flow_upload"
        )

        flow_sheet = None
        if flow_file and flow_file.name.endswith((".xlsx", ".xls")):
            try:
                sheet_list = client.list_sheets(flow_file.getvalue(), flow_file.name)
                if sheet_list:
                    flow_sheet = st.selectbox("Select Sheet", sheet_list, key="flow_sheet")
            except Exception:
                pass

        if flow_file and st.button("Create Session", type="primary", key="flow_create"):
            try:
                session = client.create_session(
                    flow_file.getvalue(),
                    flow_file.name,
                    schema=flow_schema,
                    sheet_name=flow_sheet,
                )
                st.session_state.flow_session_id = session["id"]
                st.session_state.flow_session_data = session
                st.session_state.flow_step = "review"
                st.rerun()
            except httpx.HTTPStatusError as e:
                _show_api_error(e)
            except Exception as e:
                st.error(f"Error: {e}")

    # ── Step 2: Review & Edit ──
    elif st.session_state.flow_step == "review":
        session = st.session_state.flow_session_data
        if not session:
            st.error("Session data not found. Starting over.")
            _reset_flow_session()
            st.rerun()
        else:
            st.subheader("Preview")
            preview = session.get("preview_rows", [])
            if preview:
                st.dataframe(pd.DataFrame(preview), use_container_width=True)

            st.subheader("Column Mappings")
            st.caption("Change any mapping using the dropdowns, then save or finalise.")

            mappings, unmapped = _mapping_editor(
                source_headers=session.get("source_headers", []),
                target_fields=session.get("target_fields", []),
                current_mappings=session.get("mappings", []),
            )

            # Add custom field
            st.divider()
            with st.expander("Add Custom Target Field"):
                add_col1, add_col2, add_col3 = st.columns([2, 1, 1])
                with add_col1:
                    new_field_name = st.text_input(
                        "Field Name",
                        placeholder="e.g. Broker_Notes",
                        key="flow_new_field_name",
                    )
                with add_col2:
                    new_field_type = st.selectbox(
                        "Type",
                        ["string", "date", "float", "currency"],
                        key="flow_new_field_type",
                    )
                with add_col3:
                    st.markdown("")  # spacer
                    if st.button("Add Field", key="flow_add_field"):
                        if not new_field_name or not new_field_name.strip():
                            st.error("Field name is required.")
                        elif new_field_name in session.get("target_fields", []):
                            st.error(f"Field '{new_field_name}' already exists.")
                        else:
                            try:
                                # Store the type in session state for schema creation later
                                if "flow_custom_field_types" not in st.session_state:
                                    st.session_state.flow_custom_field_types = {}
                                st.session_state.flow_custom_field_types[new_field_name] = (
                                    new_field_type
                                )

                                updated = client.add_target_fields(
                                    st.session_state.flow_session_id,
                                    fields=[new_field_name],
                                )
                                st.session_state.flow_session_data = updated
                                st.rerun()
                            except httpx.HTTPStatusError as e:
                                _show_api_error(e)
                            except Exception as e:
                                st.error(f"Error: {e}")

            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])

            with btn_col1:
                if st.button("Save Changes", key="flow_save"):
                    try:
                        updated = client.update_mappings(
                            st.session_state.flow_session_id,
                            mappings=mappings,
                            unmapped_headers=unmapped,
                        )
                        st.session_state.flow_session_data = updated
                        st.success("Mappings saved.")
                        st.rerun()
                    except httpx.HTTPStatusError as e:
                        _show_api_error(e)
                    except Exception as e:
                        st.error(f"Error: {e}")

            with btn_col2:
                if st.button("Finalise", type="primary", key="flow_finalise"):
                    try:
                        # Save current edits first, then finalise
                        client.update_mappings(
                            st.session_state.flow_session_id,
                            mappings=mappings,
                            unmapped_headers=unmapped,
                        )
                        result = client.finalise_session(
                            st.session_state.flow_session_id,
                        )
                        st.session_state.flow_session_data = result
                        st.session_state.flow_step = "results"
                        st.rerun()
                    except httpx.HTTPStatusError as e:
                        _show_api_error(e)
                    except Exception as e:
                        st.error(f"Error: {e}")

            with btn_col3:
                if st.button("Start Over", key="flow_restart_review"):
                    _reset_flow_session()
                    st.rerun()

    # ── Step 3: Results ──
    elif st.session_state.flow_step == "results":
        session = st.session_state.flow_session_data
        if not session or not session.get("result"):
            st.error("No results found. Starting over.")
            _reset_flow_session()
            st.rerun()
        else:
            result = session["result"]

            # Confidence report
            cr = result.get("confidence_report", {})
            col_a, col_b = st.columns(2)
            col_a.metric("Min Confidence", f"{cr.get('min_confidence', 0):.0%}")
            col_b.metric("Avg Confidence", f"{cr.get('avg_confidence', 0):.0%}")

            if cr.get("missing_fields"):
                st.warning(f"Missing fields: {', '.join(cr['missing_fields'])}")

            # Valid records
            valid = result.get("valid_records", [])
            errors = result.get("errors", [])

            st.subheader(f"Valid Records ({len(valid)})")
            if valid:
                valid_df = pd.DataFrame(valid)
                st.dataframe(valid_df, use_container_width=True)
                csv_data = valid_df.to_csv(index=False)
                st.download_button(
                    "Download Clean CSV",
                    csv_data,
                    file_name="mapped_output.csv",
                    mime="text/csv",
                )

            if errors:
                st.subheader(f"Validation Errors ({len(errors)})")
                for err in errors:
                    st.error(f"Row {err['row']}: {err['error']}")

            # Save as new schema
            custom_types = st.session_state.get("flow_custom_field_types", {})
            if custom_types:
                st.divider()
                st.subheader("Save as New Schema")
                st.caption(
                    f"This session added {len(custom_types)} custom field(s): "
                    f"{', '.join(custom_types.keys())}. "
                    "Save the full mapping as a reusable schema."
                )
                schema_name_input = st.text_input(
                    "Schema Name",
                    placeholder="e.g. marine_with_renewal",
                    key="flow_schema_name",
                )
                if st.button("Save Schema", key="flow_save_schema"):
                    if not schema_name_input or not schema_name_input.strip():
                        st.error("Schema name is required.")
                    else:
                        try:
                            # Build schema body from original + custom fields
                            # Get original schema fields via the API
                            original_schema_name = session.get("schema_name", "")
                            original_fields = {}
                            if original_schema_name:
                                try:
                                    schema_def = httpx.get(
                                        f"{client.base_url}/schemas/{original_schema_name}",
                                        timeout=5,
                                    )
                                    if schema_def.status_code == 200:
                                        original_fields = schema_def.json().get("fields", {})
                                except Exception:
                                    pass

                            # Add custom fields with user-selected types
                            all_fields = dict(original_fields)
                            for fname, ftype in custom_types.items():
                                all_fields[fname] = {"type": ftype}

                            schema_body = {
                                "name": schema_name_input.strip(),
                                "fields": all_fields,
                            }
                            result_schema = client.create_schema(schema_body)
                            st.success(
                                f"Schema '{result_schema['name']}' saved. "
                                "It will appear in the schema dropdown on your next session."
                            )
                        except httpx.HTTPStatusError as e:
                            _show_api_error(e)
                        except Exception as e:
                            st.error(f"Error: {e}")

            st.divider()
            if st.button("New Session", type="primary", key="flow_new"):
                _reset_flow_session()
                st.rerun()
