Your goal is to write the highest quality code possible. This means that you spend extra time reading and understanding existing code. If you are not very certain of a task or a choice, you will ask.

Whenever possible, you will avoid re-generating a code file. Generating patches to existing code is highly preferred to replacing a file with new code. If you need to regenerate a file, please confirm with me before proceeding.

All generated code should have unit tests added. Additionally, any other potentially relevant tests, including integration or end to end tests should be created. Please do not declare the task complete until you have generated all new tests, patched any existing tests as necessary, and run all tests to confirm that they pass.

If tests do not pass and you think changes to a configuration file would fix the test, please ask me whether you should update the configuration file or update the test.

Always place a summary of the completed work in the .junie/reports folder, as a markdown file with the word summary in the name and the date and time it was generated to distinguish it from other files (e.g. summary_<date>_<time>.md), with the input prompt, how you understood it, and any actions taken or code generated.

When doing research on how something works, if you write code to investigate something, instead of running Python and passing the Python code directly as an argument, please write the script out to a file in .junie/investigations, then run it from there. Name the script like a Django migration, sequentially starting from 1, along with a summary (e.g. 1_investigate_url_structure.py). Between sessions, you can start with the highest number from a past session and add 1. You may store the highest number in its own file there, or get it directly each time.

Prefer clear, expressive code over short code. Include comments regularly throughout all code to express the intent of items. Variable names should clearly express the intent and usage of the variables. When the language supports it, use type hints.

Write documentation as markdown in the documentation folder. For interactive elements, write documentation for an end user. For API elements, write documentation for a developer describing key points to interface with the code, how to use it, and considerations.

Finally, maintain a running feature list file in the main folder as FEATURES.md - before making modifications, consult this file to understand what existing features should be maintained. When adding a feature, add a line to the file with more information and confirm that no prior feature has been improperly changed by comparing the feature list with the code.

This project will use an ArcGIS-specific conda environment. Look for an environment in %LocalAppData%\ESRI\conda\envs or in %USERPROFILE%\environments

For this project, you may use C:\Users\nick.santos\AppData\Local\ESRI\conda\envs\arcgispro-py3-locator as the conda environment. To activate environments,
use the conda executables in C:\Program Files\ArcGIS\Pro\bin\Python\Scripts, including conda.exe and activate.bat 