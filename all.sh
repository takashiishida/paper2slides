#!/bin/bash

# This script takes one argument and passes it to 3 Python scripts. Finally it opens the generated PDF file.

# Function to print messages with separators
print_separator() {
    local message="$1"
    local width=$(tput cols)
    local sep_line=$(printf '=%.0s' $(seq 1 $width))
    printf "\n%s\n%s\n%s\n\n" "$sep_line" "$message" "$sep_line"
}

# Check if an argument is provided
if [ $# -eq 0 ]; then
    echo "No argument supplied"
    exit 1
fi

# Run the Python scripts with the provided argument
print_separator "starting to run arxiv2tex.py"
python arxiv2tex.py "$1"
print_separator "finished running arxiv2tex.py and starting to run tex2beamer.py"
python tex2beamer.py "$1"
print_separator "finished running tex2beamer.py and starting to run beamer2pdf.py"
python beamer2pdf.py "$1"

# Path to the PDF file
pdf_file_path="source/$1/slides.pdf"

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
