#!/usr/bin/env python3
"""
paper2slides - Unified CLI for generating presentation slides from academic papers

This script provides a unified interface for the paper2slides pipeline with subcommands:
- generate: Generate Beamer slides from arXiv paper (tex2beamer.py)
- compile: Compile LaTeX slides to PDF (beamer2pdf.py)  
- all: Full pipeline (generate + compile + open PDF)

Usage examples:
    python paper2slides.py all 2505.18102
    python paper2slides.py generate 2505.18102 --use_linter
    python paper2slides.py compile 2505.18102
"""

import argparse
import sys
import os
import subprocess
import platform
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_command(command: list, description: str, cwd: str = None) -> int:
    """
    Run a command and handle errors gracefully.
    
    Args:
        command: Command to run as list of strings
        description: Human-readable description for logging
        cwd: Working directory (optional)
        
    Returns:
        Return code of the command
    """
    logger.info(f"Running: {description}")
    logger.debug(f"Command: {' '.join(command)}")
    
    try:
        result = subprocess.run(command, cwd=cwd, check=True)
        logger.info(f"✓ {description} completed successfully")
        return result.returncode
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ {description} failed with return code {e.returncode}")
        return e.returncode
    except FileNotFoundError:
        logger.error(f"✗ Command not found: {command[0]}")
        return 1


def open_pdf(pdf_path: str) -> bool:
    """
    Open PDF file using the system's default PDF viewer.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        True if successful, False otherwise
    """
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return False
    
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["open", pdf_path], check=True)
        elif system == "Linux":
            subprocess.run(["xdg-open", pdf_path], check=True)
        elif system == "Windows":
            os.startfile(pdf_path)
        else:
            logger.warning(f"Unsupported platform: {system}. Cannot open PDF automatically.")
            return False
        
        logger.info(f"✓ Opened PDF: {pdf_path}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to open PDF: {e}")
        return False


def cmd_generate(args) -> int:
    """
    Generate Beamer slides from arXiv paper (wraps tex2beamer.py).
    
    Args:
        args: Parsed command line arguments
        
    Returns:
        Exit code
    """
    logger.info("=" * 60)
    logger.info("GENERATING SLIDES FROM ARXIV PAPER")
    logger.info("=" * 60)
    
    # Build tex2beamer command
    command = ["python", "tex2beamer.py", "--arxiv_id", args.arxiv_id]
    
    if args.use_linter:
        command.append("--use_linter")
    if args.use_pdfcrop:
        command.append("--use_pdfcrop")
    
    return run_command(command, "slide generation (tex2beamer.py)")


def cmd_compile(args) -> int:
    """
    Compile LaTeX slides to PDF (wraps beamer2pdf.py).
    
    Args:
        args: Parsed command line arguments
        
    Returns:
        Exit code
    """
    logger.info("=" * 60)
    logger.info("COMPILING SLIDES TO PDF")
    logger.info("=" * 60)
    
    command = ["python", "beamer2pdf.py", args.arxiv_id]
    return run_command(command, "PDF compilation (beamer2pdf.py)")


def cmd_all(args) -> int:
    """
    Run the full pipeline: generate slides + compile to PDF + open PDF.
    
    Args:
        args: Parsed command line arguments
        
    Returns:
        Exit code
    """
    logger.info("=" * 60)
    logger.info("RUNNING FULL PAPER2SLIDES PIPELINE")
    logger.info("=" * 60)
    
    # Step 1: Generate slides
    exit_code = cmd_generate(args)
    if exit_code != 0:
        logger.error("Pipeline failed at slide generation step")
        return exit_code
    
    # Step 2: Compile to PDF
    exit_code = cmd_compile(args)
    if exit_code != 0:
        logger.error("Pipeline failed at PDF compilation step")
        return exit_code
    
    # Step 3: Open PDF (if requested and compilation succeeded)
    if not args.no_open:
        pdf_path = f"source/{args.arxiv_id}/slides.pdf"
        open_pdf(pdf_path)
    
    logger.info("=" * 60)
    logger.info("✓ PIPELINE COMPLETED SUCCESSFULLY")
    logger.info("=" * 60)
    
    return 0


def create_parser() -> argparse.ArgumentParser:
    """
    Create the argument parser with subcommands.
    
    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog='paper2slides',
        description='Generate presentation slides from academic papers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline (default - most common usage)
  python paper2slides.py all 2505.18102
  
  # Generate slides only
  python paper2slides.py generate 2505.18102
  
  # Generate slides with linting and PDF cropping
  python paper2slides.py generate 2505.18102 --use_linter --use_pdfcrop
  
  # Compile existing slides to PDF
  python paper2slides.py compile 2505.18102
  
  # Full pipeline without opening PDF
  python paper2slides.py all 2505.18102 --no-open

Running without subcommand defaults to 'all':
  python paper2slides.py 2505.18102  # same as 'all 2505.18102'
        """
    )
    
    # Global options
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Generate subcommand
    parser_generate = subparsers.add_parser(
        'generate', 
        help='Generate Beamer slides from arXiv paper',
        description='Generate Beamer slides from an arXiv paper using LLM'
    )
    parser_generate.add_argument('arxiv_id', type=str,
                               help='ArXiv ID of the paper (e.g., 2505.18102)')
    parser_generate.add_argument('--use_linter', action='store_true',
                               help='Use ChkTeX linter for LaTeX validation')
    parser_generate.add_argument('--use_pdfcrop', action='store_true', 
                               help='Use pdfcrop to trim figure margins')
    parser_generate.set_defaults(func=cmd_generate)
    
    # Compile subcommand  
    parser_compile = subparsers.add_parser(
        'compile',
        help='Compile LaTeX slides to PDF',
        description='Compile existing Beamer slides to PDF using pdflatex'
    )
    parser_compile.add_argument('arxiv_id', type=str,
                              help='ArXiv ID (to locate slides.tex in source/ARXIV_ID/)')
    parser_compile.set_defaults(func=cmd_compile)
    
    # All subcommand (full pipeline)
    parser_all = subparsers.add_parser(
        'all',
        help='Run full pipeline: generate + compile + open PDF',
        description='Complete pipeline: generate slides, compile to PDF, and open result'
    )
    parser_all.add_argument('arxiv_id', type=str,
                          help='ArXiv ID of the paper (e.g., 2505.18102)')
    parser_all.add_argument('--use_linter', action='store_true',
                          help='Use ChkTeX linter for LaTeX validation')
    parser_all.add_argument('--use_pdfcrop', action='store_true',
                          help='Use pdfcrop to trim figure margins') 
    parser_all.add_argument('--no-open', action='store_true',
                          help='Skip opening the PDF after compilation')
    parser_all.set_defaults(func=cmd_all)
    
    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    
    # Handle convenience: if first arg is not a subcommand or global flag,
    # treat it as arxiv_id for the 'all' command
    if len(sys.argv) > 1 and sys.argv[1] not in ['generate', 'compile', 'all', '-h', '--help', '--verbose', '-v']:
        # Insert 'all' as the subcommand
        sys.argv.insert(1, 'all')
    
    # If no command specified, show help
    if len(sys.argv) == 1:
        parser.print_help()
        return 1
    
    # Parse arguments
    args = parser.parse_args()
    
    # Configure logging level
    if hasattr(args, 'verbose') and args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate that the command has a function to call
    if not hasattr(args, 'func'):
        parser.print_help()
        return 1
    
    # Check if required files exist
    script_dir = Path(__file__).parent
    tex2beamer_path = script_dir / "tex2beamer.py"
    beamer2pdf_path = script_dir / "beamer2pdf.py"
    
    if args.command in ['generate', 'all'] and not tex2beamer_path.exists():
        logger.error(f"Required file not found: {tex2beamer_path}")
        return 1
    
    if args.command in ['compile', 'all'] and not beamer2pdf_path.exists():
        logger.error(f"Required file not found: {beamer2pdf_path}")
        return 1
    
    # Execute the command
    try:
        return args.func(args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())