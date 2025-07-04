#!/bin/bash

# This script takes one argument and passes it to 3 Python scripts. Finally, it opens the generated PDF file.

# Function to print messages with separators
print_separator() {
    local message="$1"
    local width=$(tput cols)
    local sep_line=$(printf '=%.0s' $(seq 1 $width))
    printf "\n%s\n%s\n%s\n\n" "$sep_line" "$message" "$sep_line"
}

# Check if at least one argument is provided
if [ $# -lt 1 ]; then
    echo "No argument supplied"
    exit 1
fi

arxiv_id="$1"
shift

# Initialize options
use_linter=false
use_pdfcrop=false

# Parse the optional arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        use_linter)
            use_linter=true
            ;;
        use_pdfcrop)
            use_pdfcrop=true
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
    shift
done

# Run the Python scripts with the provided argument
print_separator "starting to run tex2beamer.py (using arxiv-to-prompt)"

# Build the tex2beamer command
tex2beamer_command="python tex2beamer.py --arxiv_id $arxiv_id"
if $use_linter; then
    tex2beamer_command="$tex2beamer_command --use_linter"
fi
if $use_pdfcrop; then
    tex2beamer_command="$tex2beamer_command --use_pdfcrop"
fi

# Run tex2beamer.py with the appropriate flags
eval $tex2beamer_command

print_separator "finished running tex2beamer.py and starting to run beamer2pdf.py"
python beamer2pdf.py "$arxiv_id"

# Path to the PDF file
pdf_file_path="source/$arxiv_id/slides.pdf"

# Check if PDF file exists
if [ ! -f "$pdf_file_path" ]; then
    echo "PDF file not found: $pdf_file_path"
    exit 1
fi

# Detect the operating system and open the PDF file accordingly
case "$(uname)" in
    "Linux") xdg-open "$pdf_file_path";;
    "Darwin") open "$pdf_file_path";;
    "CYGWIN"*|"MINGW"*|"MSYS"*) cmd /c start "$pdf_file_path";;
    *) echo "Unsupported operating system"; exit 1;;
esac

echo "Opened $pdf_file_path"
