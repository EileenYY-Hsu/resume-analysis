# Resume Analysis System - A resume analysis and candidate screening system built with Python, Flask, SQLite, and OpenAI API.
This project automates the process of reading PDF resumes, extracting structured information, evaluating candidate-job fit, storing analysis results, and presenting them through a web-based dashboard.
## Project Motivation
The motivation for this project came from the repetitive and time-consuming nature of resume screening. When the number of resumes increases, HR needs to read each resume, organize candidate information, and compare it with job requirements.

Therefore, I built this project to use AI to analyze resume content, structure key information such as education, experience, skills, and job match, and provide a web interface for filtering and management. The goal is to make initial resume screening more efficient and candidate comparison easier.
## Preview Screen
![Screenshot](images/preview_screen_1_chinese.png)
![Screenshot](images/preview_screen_2_chinese.png)
## Built With
This project is built with the following technologies:
- **Backend**: 
  - Python: Used for resume reading, AI analysis workflow, database operations, and Flask backend logic.
  - Flask: Used to build the web application and render the resume management dashboard.
  - SQLite: Used as the local database for storing analyzed resume data.
  - OpenAI API: Used to analyze resume content, extract structured candidate information, generate summaries, and calculate job matching scores.
  - pypdf: Used to read and extract text from PDF resume files.
