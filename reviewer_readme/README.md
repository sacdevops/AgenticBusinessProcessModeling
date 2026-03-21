# Evaluation Dataset: Agentic Business Process Modeling

Dear Reviewer,

We provide the complete evaluation dataset and supplementary materials accompanying our research paper for your assessment. This repository contains all necessary files to comprehend the deductive scoring process and to verify the empirical findings from our three design cycles.

## Folder Structure and Contents

**1. Aggregated Results (Excel Files)**
Two Excel files contain the comprehensively evaluated results from all three design cycles. These documents summarize the quantitative performance scores, completion times, and cognitive load measurements.

**2. Scoring Schema (`Scoring_schema.md`)**
This document outlines the deductive scoring methodology applied during the evaluation phase. The file details the penalty point system for structural flaws and lists the maximum points available for each of the five modeling tasks.

**3. Sample Solutions (`sample_solutions/`)**
This directory includes the reference models used to guide the assessment. These references do not represent absolute or exclusive solutions. Evaluators prioritized the underlying business logic of the modeled processes over rigid visual conformity.

**4. Raw Data (`raw/`)**
The raw directory stores the original data files gathered across the research phases, structured into three distinct subfolders corresponding to our methodology:

* **`Cycle 1/`**: Contains participant data and the generated process models from the initial exploratory study. Please note that the task descriptions and user inputs in this specific phase are in German.
* **`Cycle 2/`**: Encompasses the offline simulation data comparing the monolithic XML generation, the JSON format, the optimized custom format, and the full agentic execution. This folder also includes the raw communication logs detailing the exact prompts and responses between the application and the large language models.
* **`Cycle 3/`**: Holds the empirical results from the final participant study. The data collection occurred under strict anonymization. Consequently, this folder exclusively contains the finalized process models and the raw NASA-TLX workload evaluations without any personally identifiable information.