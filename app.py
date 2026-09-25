import os
import tempfile
import zipfile
import io

import streamlit as st

from converter import extract_data_from_pdf, create_landscape_bill

st.set_page_config(page_title="PDF Landscape Converter", page_icon="📄", layout="centered")

# --- STYLING ---
st.markdown("""
<style>
    .block-container { padding-top: 2.5rem; max-width: 780px; }

    .app-header {
        text-align: center;
        margin-bottom: 1.75rem;
    }
    .app-header h1 {
        font-size: 2rem;
        margin-bottom: 0.15rem;
    }
    .app-header p {
        color: #6b7280;
        font-size: 0.95rem;
        margin-top: 0;
    }

    div[data-testid="stFileUploader"] section {
        border: 1.5px dashed #c7cdd6;
        border-radius: 12px;
        background: #fafbfc;
    }

    .step-label {
        font-weight: 600;
        font-size: 0.95rem;
        color: #1f2937;
        margin-bottom: 0.25rem;
    }

    .stButton > button[kind="primary"] {
        border-radius: 8px;
        font-weight: 600;
        padding: 0.6rem 1.2rem;
    }
    .stButton > button[kind="secondary"] {
        border-radius: 8px;
    }

    div[data-testid="stExpander"] {
        border-radius: 10px;
        border: 1px solid #e5e7eb;
    }

    hr { margin: 1.5rem 0; }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if "results" not in st.session_state:
    st.session_state.results = []  # list of (filename, bytes)
if "errors" not in st.session_state:
    st.session_state.errors = []
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# --- HEADER ---
st.markdown("""
<div class="app-header">
    <h1>📄 PDF Landscape Converter</h1>
    <p>Turn bill PDFs into signed, landscape-formatted documents in one click.</p>
</div>
""", unsafe_allow_html=True)

# --- UPLOAD SECTION ---
with st.container(border=True):
    st.markdown('<div class="step-label">1. Select PDFs to convert</div>', unsafe_allow_html=True)
    uploaded_files = st.file_uploader(
        "Select PDFs to convert",
        type="pdf",
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
        label_visibility="collapsed",
    )

    if uploaded_files:
        st.caption(f"📎 {len(uploaded_files)} file(s) selected")

    st.markdown('<div class="step-label" style="margin-top: 1rem;">2. Optional: override signature image</div>', unsafe_allow_html=True)
    custom_sig_file = st.file_uploader(
        "Optional signature override",
        type=["png", "jpg", "jpeg"],
        key=f"sig_uploader_{st.session_state.uploader_key}",
        label_visibility="collapsed",
    )
    st.caption("Skips auto-extraction and stamps this image on every bill instead.")

    col1, col2 = st.columns([2, 1])
    with col1:
        convert_clicked = st.button("🚀 Convert All PDFs", type="primary", disabled=not uploaded_files, use_container_width=True)
    with col2:
        clear_clicked = st.button("🗑️ Clear all files", type="secondary", use_container_width=True)

# --- CLEAR ACTION ---
if clear_clicked:
    st.session_state.uploader_key += 1  # forces file_uploader widgets to reset
    st.session_state.results = []
    st.session_state.errors = []
    st.rerun()

# --- CONVERSION ---
if convert_clicked and uploaded_files:
    sig_path = None
    if custom_sig_file is not None:
        suffix = os.path.splitext(custom_sig_file.name)[1] or ".png"
        sig_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        sig_tmp.write(custom_sig_file.getbuffer())
        sig_tmp.close()
        sig_path = sig_tmp.name

    new_results = []
    new_errors = []
    progress = st.progress(0, text="Starting...")

    for i, f in enumerate(uploaded_files):
        progress.progress(i / len(uploaded_files), text=f"Converting {f.name}...")

        in_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        in_tmp.write(f.getbuffer())
        in_tmp.close()

        out_filename = f"Landscape_{f.name}"
        out_path = os.path.join(tempfile.gettempdir(), out_filename)

        try:
            data = extract_data_from_pdf(in_tmp.name)
            create_landscape_bill(data, out_path, sig_path)
            with open(out_path, "rb") as result_file:
                new_results.append((out_filename, result_file.read()))
        except Exception as e:
            new_errors.append(f"{f.name}: {e}")
        finally:
            os.remove(in_tmp.name)

    progress.progress(1.0, text="Done.")

    st.session_state.results = new_results
    st.session_state.errors = new_errors

# --- RESULTS ---
if st.session_state.errors:
    st.error("Some files failed to convert:\n" + "\n".join(st.session_state.errors))

if st.session_state.results:
    results = st.session_state.results
    st.markdown("---")
    st.markdown('<div class="step-label">3. Download</div>', unsafe_allow_html=True)
    st.success(f"✅ Converted {len(results)} file(s).")

    if len(results) == 1:
        name, content = results[0]
        st.download_button(f"⬇️ Download {name}", data=content, file_name=name, mime="application/pdf", key=f"dl_{name}", use_container_width=True)
    else:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for name, content in results:
                zf.writestr(name, content)
        st.download_button(
            "⬇️ Download all as ZIP",
            data=zip_buffer.getvalue(),
            file_name="converted_bills.zip",
            mime="application/zip",
            key="dl_zip",
            use_container_width=True,
        )
        with st.expander("Or download individually"):
            for name, content in results:
                st.download_button(f"⬇️ {name}", data=content, file_name=name, mime="application/pdf", key=f"dl_{name}", use_container_width=True)
