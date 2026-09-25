import os
import tempfile
import zipfile
import io

import streamlit as st

from converter import extract_data_from_pdf, create_landscape_bill

st.set_page_config(page_title="PDF Landscape Converter", page_icon="📄")

st.title("📄 PDF Landscape Converter")
st.caption("Upload bill PDFs to generate landscape-formatted versions with extracted data and signature.")

uploaded_files = st.file_uploader(
    "1. Select PDFs to convert",
    type="pdf",
    accept_multiple_files=True,
)

custom_sig_file = st.file_uploader(
    "2. Optional: override signature image (skips auto-extraction)",
    type=["png", "jpg", "jpeg"],
)

convert_clicked = st.button("Convert All PDFs", type="primary", disabled=not uploaded_files)

# Results live in session_state so they survive the rerun that happens
# every time a download_button is clicked - otherwise they'd vanish
# and force the user to reconvert.
if "results" not in st.session_state:
    st.session_state.results = []  # list of (filename, bytes)
if "errors" not in st.session_state:
    st.session_state.errors = []

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
        progress.progress((i) / len(uploaded_files), text=f"Converting {f.name}...")

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

    # Overwrite session_state with this run's results
    st.session_state.results = new_results
    st.session_state.errors = new_errors

# Render whatever is currently in session_state - this runs on every
# script execution, including the reruns triggered by download clicks,
# so the buttons stay visible after a click instead of disappearing.
if st.session_state.errors:
    st.error("Some files failed to convert:\n" + "\n".join(st.session_state.errors))

if st.session_state.results:
    results = st.session_state.results
    st.success(f"Converted {len(results)} file(s).")

    if len(results) == 1:
        name, content = results[0]
        st.download_button(f"Download {name}", data=content, file_name=name, mime="application/pdf", key=f"dl_{name}")
    else:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for name, content in results:
                zf.writestr(name, content)
        st.download_button(
            "Download all as ZIP",
            data=zip_buffer.getvalue(),
            file_name="converted_bills.zip",
            mime="application/zip",
            key="dl_zip",
        )
        with st.expander("Or download individually"):
            for name, content in results:
                st.download_button(f"Download {name}", data=content, file_name=name, mime="application/pdf", key=f"dl_{name}")
