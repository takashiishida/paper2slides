import streamlit as st
import os
import time
import arxiv
import re
from core import generate_slides, compile_latex, search_arxiv, edit_slides
import base64
import logging
import subprocess
import platform
from pathlib import Path
from dotenv import load_dotenv
import fitz  # PyMuPDF


def display_pdf(file_path):
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode("utf-8")
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)


def display_pdf_as_images(file_path: str):
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        st.error(f"Failed to open PDF: {e}")
        return

    page_count = doc.page_count
    st.caption(f"Pages: {page_count}")

    # Heuristic: render all if small doc, otherwise let user choose
    render_all_default = page_count <= 15
    render_all = st.checkbox("Render all pages", value=render_all_default)

    zoom = 2.0
    mat = fitz.Matrix(zoom, zoom)

    if render_all:
        for i in range(page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            st.image(pix.tobytes("png"), use_container_width=True, caption=f"Page {i+1}")
    else:
        page_num = st.slider("Page", min_value=1, max_value=page_count, value=1)
        page = doc.load_page(page_num - 1)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        st.image(pix.tobytes("png"), use_container_width=True, caption=f"Page {page_num}")

    doc.close()


def get_arxiv_id_from_query(query: str) -> str | None:
    """
    Resolve query to arxiv_id, similar to paper2slides.py get_arxiv_id function.
    If query is already a valid arXiv ID, return it directly.
    Otherwise, perform search and let user select from results.
    """
    # Regex to check for valid arXiv ID format
    arxiv_id_pattern = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
    if arxiv_id_pattern.match(query):
        logging.info(f"Valid arXiv ID provided: {query}")
        return query

    # If not a direct ID, we need to search and let user choose
    # This will be handled by the UI search flow
    return None


def run_generate_step(arxiv_id: str, api_key: str, model_name: str) -> bool:
    """
    Step 1: Generate slides from arXiv paper (equivalent to cmd_generate)
    """
    logging.info("=" * 60)
    logging.info("GENERATING SLIDES FROM ARXIV PAPER")
    logging.info("=" * 60)

    success = generate_slides(
        arxiv_id=arxiv_id,
        use_linter=False,
        use_pdfcrop=False,
        api_key=api_key,
        model_name=model_name,
    )

    if success:
        logging.info("✓ Slide generation completed successfully")
    else:
        logging.error("✗ Slide generation failed")

    return success


def run_compile_step(arxiv_id: str, pdflatex_path: str) -> bool:
    """
    Step 2: Compile LaTeX slides to PDF (equivalent to cmd_compile)
    """
    logging.info("=" * 60)
    logging.info("COMPILING SLIDES TO PDF")
    logging.info("=" * 60)

    success = compile_latex(
        tex_file_path="slides.tex",
        output_directory=f"source/{arxiv_id}/",
        pdflatex_path=pdflatex_path,
    )

    if success:
        logging.info("✓ PDF compilation completed successfully")
    else:
        logging.error("✗ PDF compilation failed")

    return success


def run_full_pipeline(
    arxiv_id: str,
    api_key: str,
    model_name: str,
    pdflatex_path: str,
) -> bool:
    """
    Full pipeline: generate + compile (equivalent to cmd_all, minus opening PDF)
    """
    logging.info("=" * 60)
    logging.info("RUNNING FULL PAPER2SLIDES PIPELINE")
    logging.info("=" * 60)

    # Step 1: Generate slides
    if not run_generate_step(arxiv_id, api_key, model_name):
        logging.error("Pipeline failed at slide generation step")
        return False

    # Step 2: Compile to PDF
    if not run_compile_step(arxiv_id, pdflatex_path):
        logging.error("Pipeline failed at PDF compilation step")
        return False

    # Step 3: Verify PDF exists (we don't auto-open in webui)
    pdf_path = f"source/{arxiv_id}/slides.pdf"
    if os.path.exists(pdf_path):
        logging.info("=" * 60)
        logging.info("✓ PIPELINE COMPLETED SUCCESSFULLY")
        logging.info("=" * 60)
        return True
    else:
        logging.error("PDF not found after compilation")
        return False


def main():
    st.set_page_config(layout="wide")

    st.title("📄 Paper2Slides")

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "arxiv_id" not in st.session_state:
        st.session_state.arxiv_id = None
    if "pdf_path" not in st.session_state:
        st.session_state.pdf_path = None
    if "pipeline_status" not in st.session_state:
        st.session_state.pipeline_status = (
            "ready"  # ready, generating, compiling, completed, failed
        )
    if "pdflatex_path" not in st.session_state:
        st.session_state.pdflatex_path = "pdflatex"
    if "openai_api_key" not in st.session_state:

        load_dotenv(override=True)
        st.session_state.openai_api_key = os.getenv("OPENAI_API_KEY", "")
    if "model_name" not in st.session_state:
        st.session_state.model_name = "gpt-4.1"

    if "run_full_pipeline" not in st.session_state:
        st.session_state.run_full_pipeline = False

    # Configure logger
    if "logger_configured" not in st.session_state:
        logger = logging.getLogger()
        if not logger.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(levelname)s - %(message)s",
                datefmt="%H:%M:%S",
            )
        st.session_state.logger_configured = True

    # Sidebar for paper search and settings
    with st.sidebar:
        st.header("Search Paper")
        query = st.text_input("Enter arXiv ID or search query:", key="query_input")

        st.header("Pipeline Settings")
        st.session_state.openai_api_key = st.text_input(
            "API Key (OpenAI or DashScope)",
            type="password",
            value=st.session_state.openai_api_key,
        )
        st.caption(
            "If left empty, keys from .env are used: OPENAI_API_KEY > DASHSCOPE_API_KEY."
        )
        st.session_state.model_name = st.text_input(
            "Model Name (e.g., gpt-4.1-2025-04-14 or qwen-plus)",
            value=st.session_state.model_name,
        )
        st.session_state.pdflatex_path = st.text_input(
            "Path to pdflatex compiler", value=st.session_state.pdflatex_path
        )

        # Pipeline control buttons
        st.header("Pipeline Control")

        if st.button("Search Papers", key="search_button"):
            st.session_state.arxiv_id = None
            st.session_state.pdf_path = None
            st.session_state.messages = []
            st.session_state.pipeline_status = "ready"

            # Check if query is direct arxiv_id or needs search
            direct_id = get_arxiv_id_from_query(query)
            if direct_id:
                st.session_state.arxiv_id = direct_id
            else:
                results = search_arxiv(query)
                if results:
                    st.session_state.search_results = results
                else:
                    st.warning("No papers found.")

        # Show search results for selection
        if "search_results" in st.session_state:
            st.subheader("Search Results")
            for i, result in enumerate(st.session_state.search_results):
                if st.button(
                    f"**{result.title[:60]}...** by {result.authors[0].name} et al.",
                    key=f"select_{i}",
                ):
                    st.session_state.arxiv_id = result.get_short_id()
                    del st.session_state.search_results
                    st.rerun()

        # Pipeline execution buttons (only show if arxiv_id is selected)
        if st.session_state.arxiv_id:
            st.success(f"Selected: {st.session_state.arxiv_id}")

            # Only allow running if not currently processing
            can_run = st.session_state.pipeline_status in [
                "ready",
                "completed",
                "failed",
            ]

            if st.button(
                "🚀 Run Full Pipeline",
                key="run_full",
                disabled=not can_run,
                help="Generate slides + Compile PDF (equivalent to 'python paper2slides.py all <arxiv_id>')",
            ):
                st.session_state.pipeline_status = "generating"
                st.session_state.pdf_path = None
                st.session_state.run_full_pipeline = True
                st.rerun()

            col1, col2 = st.columns(2)
            with col1:
                if st.button(
                    "📝 Generate Only",
                    key="run_generate",
                    disabled=not can_run,
                    help="Generate slides only (equivalent to 'python paper2slides.py generate <arxiv_id>')",
                ):
                    st.session_state.pipeline_status = "generating"
                    st.session_state.pdf_path = None
                    st.session_state.run_full_pipeline = False
                    st.rerun()

            with col2:
                slides_exist = os.path.exists(
                    f"source/{st.session_state.arxiv_id}/slides.tex"
                )
                if st.button(
                    "🔨 Compile Only",
                    key="run_compile",
                    disabled=not can_run or not slides_exist,
                    help="Compile existing slides to PDF (equivalent to 'python paper2slides.py compile <arxiv_id>')",
                ):
                    st.session_state.pipeline_status = "compiling"
                    st.session_state.run_full_pipeline = False
                    st.rerun()

    # Main area for chat and PDF viewer
    col1, col2 = st.columns(2)

    with col1:
        st.header("Interactive Editing")

        # Only allow editing if pipeline is completed and PDF exists
        if (
            st.session_state.pipeline_status == "completed"
            and st.session_state.arxiv_id
            and os.path.exists(f"source/{st.session_state.arxiv_id}/slides.tex")
        ):

            # Display chat messages
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # Chat input
            if prompt := st.chat_input("Your instructions to edit the slides..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("Editing slides..."):
                        slides_tex_path = (
                            f"source/{st.session_state.arxiv_id}/slides.tex"
                        )
                        with open(slides_tex_path, "r") as f:
                            beamer_code = f.read()

                        new_beamer_code = edit_slides(
                            beamer_code,
                            prompt,
                            st.session_state.openai_api_key,
                            st.session_state.model_name,
                        )

                        if new_beamer_code:
                            with open(slides_tex_path, "w") as f:
                                f.write(new_beamer_code)
                            st.info("Recompiling PDF with changes...")
                            if run_compile_step(
                                st.session_state.arxiv_id,
                                st.session_state.pdflatex_path,
                            ):
                                st.success("PDF recompiled successfully!")
                                st.session_state.pdf_path = (
                                    f"source/{st.session_state.arxiv_id}/slides.pdf"
                                )
                                st.rerun()
                            else:
                                st.error("Failed to recompile PDF.")
                        else:
                            st.error("Failed to edit slides.")
        else:
            st.info(
                "Interactive editing will be available after successful pipeline completion."
            )

    with col2:
        st.header("Pipeline Status & Results")

        # Execute pipeline based on status
        if (
            st.session_state.pipeline_status == "generating"
            and st.session_state.arxiv_id
        ):
            with st.spinner("🔄 Running slide generation..."):
                success = run_generate_step(
                    st.session_state.arxiv_id,
                    st.session_state.openai_api_key,
                    st.session_state.model_name,
                )

                if success:
                    st.success("✅ Slide generation completed!")
                    # Check if this was part of full pipeline or generate-only
                    if st.session_state.get("run_full_pipeline", False):
                        st.session_state.pipeline_status = "compiling"
                    else:
                        st.session_state.pipeline_status = "completed"
                else:
                    st.error("❌ Slide generation failed!")
                    st.session_state.pipeline_status = "failed"
                st.rerun()

        elif (
            st.session_state.pipeline_status == "compiling"
            and st.session_state.arxiv_id
        ):
            with st.spinner("🔄 Compiling PDF..."):
                success = run_compile_step(
                    st.session_state.arxiv_id, st.session_state.pdflatex_path
                )

                if success:
                    st.success("✅ PDF compilation completed!")
                    st.session_state.pipeline_status = "completed"
                    st.session_state.pdf_path = (
                        f"source/{st.session_state.arxiv_id}/slides.pdf"
                    )
                else:
                    st.error("❌ PDF compilation failed!")
                    st.session_state.pipeline_status = "failed"
                st.rerun()

        # Show PDF if available
        if (
            st.session_state.pdf_path
            and os.path.exists(st.session_state.pdf_path)
            and st.session_state.pipeline_status == "completed"
        ):

            st.subheader("📄 Generated Slides")
            with open(st.session_state.pdf_path, "rb") as f:
                st.download_button(
                    "📥 Download PDF",
                    f,
                    file_name=f"{st.session_state.arxiv_id}_slides.pdf",
                    mime="application/pdf",
                )
            display_pdf_as_images(st.session_state.pdf_path)

        elif st.session_state.pipeline_status == "ready":
            st.info("🎯 Select a paper and run the pipeline to generate slides.")
        elif st.session_state.pipeline_status == "failed":
            st.error("❌ Pipeline failed. Check the logs above for details.")
        else:
            st.info("📄 Generated PDF will be displayed here when ready.")


if __name__ == "__main__":
    main()
