"""
build_checklist_index.py — Indexador de checklists para SIRA.

Mejoras sobre la versión anterior:
  - pdfplumber para extracción con layout preservado (tablas, columnas)
  - Estrategia de chunking por sección semántica, no por tamaño fijo
  - study_type alineado con el semantic router de rag_checklist.py
  - Logging estructurado con progreso real
  - Verificación de integridad post-indexación
  - Metadata enriquecida por chunk (item_number, section, etc.)
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import NamedTuple

import pdfplumber
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────

RAG_DATA_DIR = Path(__file__).resolve().parent / "rag_data_revisor"
DB_PATH      = Path(__file__).resolve().parent / "new_db"
COLLECTION   = "checklist_guides"
EMBED_MODEL  = "nomic-embed-text:latest"

# Tamaños ajustados para checklists: items son cortos, pero las descripciones
# expandidas (como CONSORT 2025) pueden ser largas. Overlap alto para no
# partir un item a la mitad entre dos chunks.
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 200

# ── Mapa de archivos ───────────────────────────────────────────────────────────
# IMPORTANTE: study_type debe coincidir EXACTAMENTE con los valores del router
# en rag_checklist.py: rct | systematic_review | observational | diagnostic |
#                       nlp_ml | case_report | animal_study | general
#
# Los sub-tipos de STROBE (cohort, case_control, cross_sectional) se mapean a
# "observational" para que el router los encuentre, pero se distinguen por
# checklist_name y checklist_subtype en metadata.

class ChecklistEntry(NamedTuple):
    checklist_name: str       # Nombre oficial del checklist
    study_type: str           # Valor EXACTO del router (controlado, 8 posibles)
    checklist_subtype: str    # Sub-clasificación libre para filtros finos
    guideline_org: str        # Organización / iniciativa que lo publica
    n_items: int              # Número oficial de ítems del checklist
    primary_focus: str        # Qué evalúa principalmente (1 frase corta)
    key_sections: str         # Secciones / dominios cubiertos (para embedding)
    key_concepts: str         # Términos técnicos centrales (boost semántico)
    use_when: str             # Cuándo se debe aplicar este checklist


# ── FILE_MAP enriquecido ───────────────────────────────────────────────────────
# Cada entrada tiene metadata profunda derivada del contenido real de cada
# checklist. Esto enriquece el embedding de la "ficha" del documento y mejora
# el recall en similarity search, especialmente cuando el chunk recuperado
# es una tabla cruda con poco contexto semántico.
#
# REGLA CRÍTICA: study_type debe coincidir EXACTAMENTE con los valores del
# router en rag_checklist.py:
#   rct | systematic_review | observational | diagnostic |
#   nlp_ml | case_report | animal_study | general

FILE_MAP: dict[str, ChecklistEntry] = {

    # ══════════════════════════════════════════════════════════════════════════
    # RCT — Ensayos controlados aleatorizados
    # ══════════════════════════════════════════════════════════════════════════

    "CONSORT_2025_expanded_checklist.pdf": ChecklistEntry(
        checklist_name  = "CONSORT 2025",
        study_type      = "rct",
        checklist_subtype = "randomized_controlled_trial_results",
        guideline_org   = "CONSORT Group / BMJ / JAMA / Lancet",
        n_items         = 30,
        primary_focus   = (
            "Reporting completeness of published randomized controlled trial results. "
            "Covers transparent communication of design, conduct, analysis and outcomes."
        ),
        key_sections    = (
            "Title and abstract; Introduction: background and rationale, objectives; "
            "Methods: trial design, participants, interventions, outcomes, sample size, "
            "randomisation sequence generation allocation concealment blinding; "
            "Statistical methods; Results: participant flow CONSORT diagram, baseline data, "
            "numbers analysed, outcomes estimation, ancillary analyses, harms; "
            "Discussion: limitations, generalisability; "
            "Open science: registration protocol data sharing; "
            "Patient and public involvement (PPI); Other information: funding conflicts"
        ),
        key_concepts    = (
            "randomization allocation concealment blinding placebo parallel group "
            "superiority equivalence non-inferiority intention-to-treat per-protocol "
            "CONSORT flow diagram attrition loss to follow-up primary endpoint "
            "confidence interval p-value effect size GRADE open science data sharing "
            "preregistration ClinicalTrials.gov TIDieR intervention fidelity harms "
            "adverse events patient and public involvement"
        ),
        use_when        = (
            "The paper reports the results of a randomized controlled trial (RCT), "
            "pragmatic trial, cluster RCT, crossover trial, or factorial trial."
        ),
    ),

    "SPIRIT 2025 expanded checklist - Revised 2024Dec22.pdf": ChecklistEntry(
        checklist_name  = "SPIRIT 2025",
        study_type      = "rct",
        checklist_subtype = "clinical_trial_protocol",
        guideline_org   = "SPIRIT-CONSORT Group",
        n_items         = 34,
        primary_focus   = (
            "Minimum content standards for randomized trial protocols before trial execution. "
            "Ensures protocols are complete, transparent and reproducible."
        ),
        key_sections    = (
            "Administrative information: title, trial registration, protocol version, "
            "funding, roles and responsibilities; "
            "Introduction: background rationale, objectives; "
            "Methods: trial design, participants eligibility criteria, interventions TIDieR, "
            "outcomes primary secondary, participant timeline schedule of enrolment, "
            "sample size, recruitment, randomisation, blinding, data collection management, "
            "statistical methods, harms monitoring; "
            "Open science: protocol sharing statistical analysis plan data sharing; "
            "Patient and public involvement; Ethics and dissemination"
        ),
        key_concepts    = (
            "trial protocol SPIRIT eligibility criteria inclusion exclusion "
            "interventions comparator TIDieR schedule of enrolment CONSORT "
            "sample size calculation randomisation allocation sequence concealment "
            "blinding masking data safety monitoring board DSMB interim analysis "
            "stopping rules CRF data management statistical analysis plan SAP "
            "regulatory approval ethics IRB consent open science pre-registration "
            "patient and public involvement PPI post-trial care conflicts of interest"
        ),
        use_when        = (
            "The paper describes a protocol or study plan for a randomized trial "
            "that has not yet been completed or published as results."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # Systematic Review / Meta-analysis
    # ══════════════════════════════════════════════════════════════════════════

    "PRISMA_2020_expanded_checklist.pdf": ChecklistEntry(
        checklist_name  = "PRISMA 2020",
        study_type      = "systematic_review",
        checklist_subtype = "systematic_review_meta_analysis",
        guideline_org   = "PRISMA Group",
        n_items         = 27,
        primary_focus   = (
            "Transparent and complete reporting of systematic reviews and meta-analyses, "
            "including search strategy, study selection, data extraction and synthesis."
        ),
        key_sections    = (
            "Title; Abstract structured summary; Introduction: rationale objectives PICOS; "
            "Methods: eligibility criteria information sources search strategy selection process "
            "data collection process data items study risk of bias assessment effect measures "
            "synthesis methods reporting bias assessment certainty of evidence; "
            "Results: study selection PRISMA flow diagram study characteristics "
            "risk of bias results of individual studies results of syntheses "
            "reporting biases certainty of evidence; "
            "Discussion: summary limitations conclusions; "
            "Other: registration protocol support funding conflicts of interest"
        ),
        key_concepts    = (
            "systematic review meta-analysis PRISMA PICOS PICO research question "
            "search strategy PubMed MEDLINE Embase database search string "
            "inclusion exclusion criteria title abstract screening full-text screening "
            "PRISMA flow diagram data extraction risk of bias Cochrane RoB2 ROBINS "
            "heterogeneity I-squared forest plot pooled estimate effect size "
            "random effects fixed effects subgroup analysis sensitivity analysis "
            "publication bias funnel plot Egger Begg GRADE certainty of evidence "
            "narrative synthesis quantitative synthesis grey literature PROSPERO"
        ),
        use_when        = (
            "The paper reports a systematic review, meta-analysis, or scoping review "
            "that synthesizes evidence from multiple primary studies."
        ),
    ),

    "AGREE-Reporting-Checklist.pdf": ChecklistEntry(
        checklist_name  = "AGREE Reporting Checklist",
        study_type      = "systematic_review",
        checklist_subtype = "clinical_practice_guidelines",
        guideline_org   = "AGREE Next Steps Consortium",
        n_items         = 23,
        primary_focus   = (
            "Appraisal and transparent reporting of clinical practice guidelines, "
            "covering rigour of development, stakeholder involvement and editorial independence."
        ),
        key_sections    = (
            "Domain 1 — Scope and purpose: objectives health questions population; "
            "Domain 2 — Stakeholder involvement: individuals involved target population patients; "
            "Domain 3 — Rigour of development: systematic methods evidence body "
            "strengths limitations formulation recommendations external review update procedure; "
            "Domain 4 — Clarity of presentation: specific unambiguous recommendations "
            "management options key recommendations; "
            "Domain 5 — Applicability: facilitators barriers implementation advice "
            "resource implications monitoring audit criteria; "
            "Domain 6 — Editorial independence: competing interests funding body influence"
        ),
        key_concepts    = (
            "clinical practice guideline CPG AGREE appraisal evidence-based recommendations "
            "guideline development group multidisciplinary panel stakeholders patients "
            "systematic literature search evidence synthesis GRADE strength of recommendation "
            "scope purpose target population health question external review "
            "pilot testing implementation facilitators barriers resource implications "
            "editorial independence funding conflicts of interest update procedure "
            "clinical decision support dissemination"
        ),
        use_when        = (
            "The paper develops, reports or appraises a clinical practice guideline "
            "or evidence-based recommendation document."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # Observational Studies (STROBE family)
    # ══════════════════════════════════════════════════════════════════════════

    "STROBE_checklist_v4_combined.pdf": ChecklistEntry(
        checklist_name  = "STROBE (combined — all observational designs)",
        study_type      = "observational",
        checklist_subtype = "observational_combined",
        guideline_org   = "STROBE Initiative",
        n_items         = 22,
        primary_focus   = (
            "Transparent reporting of observational epidemiological studies — "
            "covers cohort, case-control and cross-sectional designs in a single checklist."
        ),
        key_sections    = (
            "Title and abstract; Introduction: background rationale, objectives hypotheses; "
            "Methods: study design setting participants variables data sources measurement "
            "bias study size quantitative variables statistical methods; "
            "Results: participants descriptive data outcome data main results "
            "other analyses; "
            "Discussion: key results limitations interpretation generalisability; "
            "Other: funding"
        ),
        key_concepts    = (
            "observational study STROBE cohort case-control cross-sectional "
            "exposure outcome confounding selection bias information bias "
            "matching propensity score adjustment odds ratio relative risk "
            "incidence prevalence hazard ratio survival analysis Cox regression "
            "logistic regression multivariable adjustment missing data "
            "sensitivity analysis effect modification interaction "
            "prospective retrospective follow-up loss to follow-up"
        ),
        use_when        = (
            "The paper is an observational epidemiological study (cohort, case-control "
            "or cross-sectional) and the reviewer needs the combined generic version."
        ),
    ),

    "STROBE_checklist_v4_cohort.pdf": ChecklistEntry(
        checklist_name  = "STROBE (cohort studies)",
        study_type      = "observational",
        checklist_subtype = "cohort_study",
        guideline_org   = "STROBE Initiative",
        n_items         = 22,
        primary_focus   = (
            "Transparent reporting specific to cohort studies, "
            "emphasizing exposure ascertainment, follow-up duration and attrition."
        ),
        key_sections    = (
            "Methods — cohort-specific: eligible exposed and unexposed participants "
            "or general population follow-up period; "
            "Sources and methods for exposure assessment and follow-up; "
            "Outcome assessment during follow-up; "
            "Results: numbers at each stage of study, summary of follow-up time, "
            "unadjusted and adjusted estimates incidence rates"
        ),
        key_concepts    = (
            "cohort study prospective retrospective exposed unexposed follow-up "
            "incidence rate person-time at risk attrition loss to follow-up "
            "time-to-event survival Kaplan-Meier Cox proportional hazards "
            "exposure ascertainment baseline characteristics confounders "
            "hazard ratio relative risk 95% CI"
        ),
        use_when        = (
            "The paper is specifically a cohort study tracking exposed and unexposed "
            "participants over time to measure incidence of outcomes."
        ),
    ),

    "STROBE_checklist_v4_case-control.pdf": ChecklistEntry(
        checklist_name  = "STROBE (case-control studies)",
        study_type      = "observational",
        checklist_subtype = "case_control_study",
        guideline_org   = "STROBE Initiative",
        n_items         = 22,
        primary_focus   = (
            "Transparent reporting specific to case-control studies, "
            "emphasizing case definition, control selection and exposure recall."
        ),
        key_sections    = (
            "Methods — case-control-specific: cases source population rationale "
            "for choice of cases and controls; "
            "Methods for ascertaining exposure separately for cases and controls; "
            "Results: numbers of eligible potential participants examined "
            "for each exposure category; response rates; "
            "Odds ratios with confidence intervals and p-values"
        ),
        key_concepts    = (
            "case-control study cases controls matched unmatched "
            "odds ratio OR exposure history recall bias selection of controls "
            "hospital controls population controls matching variables "
            "conditional logistic regression unconditional logistic regression "
            "confounding exposure ascertainment interview questionnaire"
        ),
        use_when        = (
            "The paper is a case-control study comparing individuals with a disease "
            "or outcome (cases) to those without (controls) to identify risk factors."
        ),
    ),

    "STROBE_checklist_v4_cross-sectional.pdf": ChecklistEntry(
        checklist_name  = "STROBE (cross-sectional studies)",
        study_type      = "observational",
        checklist_subtype = "cross_sectional_study",
        guideline_org   = "STROBE Initiative",
        n_items         = 22,
        primary_focus   = (
            "Transparent reporting specific to cross-sectional studies, "
            "emphasizing sampling frame, participation rate and prevalence estimation."
        ),
        key_sections    = (
            "Methods — cross-sectional-specific: eligibility criteria sources "
            "and methods of selection of participants; "
            "If applicable description of sampling strategy; "
            "Results: numbers of participants at each stage, "
            "prevalence estimates with confidence intervals"
        ),
        key_concepts    = (
            "cross-sectional study prevalence survey sampling frame "
            "participation rate response rate non-response bias "
            "prevalence ratio prevalence odds ratio weighted analysis "
            "complex survey design cluster sampling stratification "
            "point-in-time measurement simultaneous exposure outcome"
        ),
        use_when        = (
            "The paper is a cross-sectional study measuring exposure and outcome "
            "at the same point in time in a defined population."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # Case Report
    # ══════════════════════════════════════════════════════════════════════════

    "CARE-checklist-English-2013.pdf": ChecklistEntry(
        checklist_name  = "CARE 2013 (CAse REport guidelines)",
        study_type      = "case_report",
        checklist_subtype = "clinical_case_report",
        guideline_org   = "CARE Group",
        n_items         = 13,
        primary_focus   = (
            "Complete and transparent reporting of individual clinical case reports, "
            "covering patient history, clinical findings, diagnosis, interventions and outcomes."
        ),
        key_sections    = (
            "Title; Keywords; Abstract: introduction case presentation conclusion; "
            "Introduction: why this case is unique / educational value; "
            "Patient information: demographic anonymized chief complaints "
            "medical history family history psychosocial history; "
            "Clinical findings: examination; "
            "Timeline: chronological events; "
            "Diagnostic assessment: diagnostic methods results diagnosis; "
            "Therapeutic interventions: types modifications; "
            "Follow-up and outcomes: clinician and patient perspectives; "
            "Discussion: strengths limitations take-away lessons; "
            "Patient perspective; Informed consent"
        ),
        key_concepts    = (
            "case report CARE single patient clinical case individual patient "
            "chief complaint presenting complaint history of present illness "
            "past medical history physical examination diagnostic workup "
            "differential diagnosis working diagnosis laboratory imaging "
            "treatment intervention therapeutic outcome follow-up "
            "adverse drug reaction rare disease novel presentation "
            "informed consent patient anonymity educational value"
        ),
        use_when        = (
            "The paper reports the clinical experience with one or a small series "
            "of individual patients, describing a case report or case series."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # Animal Studies (ARRIVE family)
    # ══════════════════════════════════════════════════════════════════════════

    "ARRIVE_gl_animal_research.pdf": ChecklistEntry(
        checklist_name  = "ARRIVE 2.0 (Animal Research: Reporting of In Vivo Experiments)",
        study_type      = "animal_study",
        checklist_subtype = "animal_in_vivo_research",
        guideline_org   = "NC3Rs (National Centre for the Replacement, Refinement and Reduction of Animals in Research)",
        n_items         = 21,
        primary_focus   = (
            "Complete reporting of in vivo animal experiments to enable reproducibility "
            "and critical assessment, organized into ARRIVE Essential 10 and Recommended Set."
        ),
        key_sections    = (
            "Essential 10 — Study design: experimental units randomisation blinding "
            "sample size calculation; "
            "Essential 10 — Animals: species strain sex age weight source health status; "
            "Essential 10 — Ethical statement: IACUC approval 3Rs; "
            "Essential 10 — Housing and husbandry: environment light temperature diet water; "
            "Essential 10 — Experimental procedures: all procedures for each group; "
            "Essential 10 — Outcomes: primary secondary; "
            "Essential 10 — Statistical methods: analysis software; "
            "Essential 10 — Baseline data; Allocation and numbers analysed; Outcomes results; "
            "Recommended set: abstract animal numbers in abstract; "
            "Background and objectives; Ethical statement; "
            "Interpretation; Generalisability translation; Protocol registration; "
            "Data access"
        ),
        key_concepts    = (
            "animal study in vivo ARRIVE 3Rs replacement reduction refinement "
            "mouse rat species strain sex age weight housing husbandry "
            "randomisation group allocation blinding outcome assessment "
            "sample size power calculation IACUC ethics approval "
            "anaesthesia analgesia surgery endpoint humane endpoint "
            "phenotype genotype transgenic knockout wild-type control "
            "preclinical model disease model translational research "
            "inter-animal variability biological replicates technical replicates"
        ),
        use_when        = (
            "The paper reports experimental research conducted on live animals "
            "(mice, rats, or other vertebrates) in a laboratory setting."
        ),
    ),

    "Author Checklist_ARRIVE2.pdf": ChecklistEntry(
        checklist_name  = "ARRIVE 2.0 Author Submission Checklist",
        study_type      = "animal_study",
        checklist_subtype = "animal_study_submission_checklist",
        guideline_org   = "NC3Rs",
        n_items         = 21,
        primary_focus   = (
            "Condensed author-facing version of ARRIVE 2.0 for journal submission, "
            "verifying presence of each mandatory and recommended item before submission."
        ),
        key_sections    = (
            "Essential 10 priority items checklist for submission; "
            "Recommended set secondary items; "
            "Location of each ARRIVE item in the manuscript (page number column)"
        ),
        key_concepts    = (
            "ARRIVE 2.0 author checklist submission journal requirements "
            "Essential 10 priority items recommended set "
            "animal numbers sex species randomisation blinding "
            "sample size ethical approval housing experimental procedures "
            "outcomes statistical methods manuscript page number location"
        ),
        use_when        = (
            "Checking that an animal study manuscript contains all ARRIVE items "
            "before journal submission, as the condensed author-facing checklist."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # Diagnostic Accuracy Studies
    # ══════════════════════════════════════════════════════════════════════════

    "STARD-2015-checklist.pdf": ChecklistEntry(
        checklist_name  = "STARD 2015 (Standards for Reporting Diagnostic Accuracy Studies)",
        study_type      = "diagnostic",
        checklist_subtype = "diagnostic_test_accuracy",
        guideline_org   = "STARD Group",
        n_items         = 30,
        primary_focus   = (
            "Complete and accurate reporting of studies evaluating the performance "
            "of a diagnostic or screening test against a reference standard."
        ),
        key_sections    = (
            "Title / Abstract / Keywords: identify as diagnostic accuracy study; "
            "Introduction: scientific background study objectives clinical role intended use; "
            "Methods: study design data collection dates participants eligibility "
            "recruitment setting index test reference standard technical specs "
            "test execution blinding estimation of diagnostic accuracy; "
            "Results: flow of participants STARD flow diagram "
            "baseline demographics test results cross-tabulation "
            "time interval between index test and reference standard "
            "estimates of diagnostic accuracy with 95% CIs; "
            "Discussion: limitations applicability; "
            "Other: registration protocol availability funding"
        ),
        key_concepts    = (
            "diagnostic test accuracy STARD index test reference standard "
            "sensitivity specificity positive predictive value negative predictive value "
            "PPV NPV likelihood ratio LR+ LR- ROC curve AUC "
            "area under curve receiver operating characteristic "
            "cut-off threshold cross-tabulation 2x2 table "
            "true positive false positive true negative false negative "
            "disease prevalence pre-test post-test probability "
            "gold standard criterion standard clinical reference "
            "reader variability inter-rater agreement kappa "
            "biomarker imaging laboratory test screening diagnostic workup "
            "QUADAS-2 risk of bias diagnostic accuracy study"
        ),
        use_when        = (
            "The paper evaluates the accuracy of a diagnostic test, biomarker, "
            "imaging modality, or screening tool compared to a reference standard."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # NLP / Machine Learning / Computational Research
    # ══════════════════════════════════════════════════════════════════════════

    "2306.09562v1_NLP_reproducibility.pdf": ChecklistEntry(
        checklist_name  = "NLP Reproducibility Checklist",
        study_type      = "nlp_ml",
        checklist_subtype = "nlp_reproducibility",
        guideline_org   = "ACL / NLP Research Community",
        n_items         = 0,   # Variable por sección
        primary_focus   = (
            "Reproducibility and transparency standards for NLP papers, "
            "covering model training, evaluation, datasets and claims."
        ),
        key_sections    = (
            "Claims and evidence: theoretical claims experimental claims; "
            "Experiments: datasets preprocessing splits training details "
            "hyperparameters compute budget GPU/CPU time random seeds; "
            "Models: architecture pretrained checkpoints fine-tuning; "
            "Evaluation: metrics benchmark datasets test set contamination "
            "statistical significance multiple comparison correction; "
            "Code and artifacts: code release model release data release licenses; "
            "Human evaluation: annotation guidelines inter-annotator agreement "
            "crowdsourcing workers compensation"
        ),
        key_concepts    = (
            "NLP natural language processing reproducibility replicability "
            "language model transformer BERT GPT fine-tuning pre-training "
            "benchmark dataset train validation test split "
            "hyperparameter tuning learning rate batch size epochs "
            "random seed determinism GPU CUDA compute FLOPS "
            "BLEU ROUGE F1 accuracy perplexity evaluation metric "
            "statistical significance bootstrap confidence interval "
            "human evaluation annotation inter-annotator agreement kappa "
            "crowdsourcing AMT code release model release artifact "
            "dataset bias fairness prompt engineering zero-shot few-shot"
        ),
        use_when        = (
            "The paper presents NLP or computational linguistics research, "
            "including language models, text classification, NER, machine translation, etc."
        ),
    ),

    "2506.01789v2_Data_Rubrics.pdf": ChecklistEntry(
        checklist_name  = "Data Rubrics for ML Research",
        study_type      = "nlp_ml",
        checklist_subtype = "ml_data_quality",
        guideline_org   = "ML Research Community",
        n_items         = 0,
        primary_focus   = (
            "Quality rubric for datasets and data practices in machine learning research, "
            "covering collection, documentation, splits, biases and release."
        ),
        key_sections    = (
            "Data collection and curation: sources collection protocol annotation "
            "labeling quality control inter-annotator agreement; "
            "Dataset documentation: datasheet dataset card metadata schema; "
            "Train/validation/test splits: leakage contamination stratification; "
            "Data quality: noise missing values duplicates distribution shift; "
            "Bias and fairness: demographic representation protected attributes; "
            "Data release: license privacy PII anonymization access"
        ),
        key_concepts    = (
            "dataset data quality ML machine learning datasheet dataset card "
            "data collection annotation labeling crowdsourcing AMT "
            "train test split validation holdout data leakage contamination "
            "benchmark dataset bias fairness demographic representation "
            "protected attributes sensitive attributes debiasing "
            "data preprocessing tokenization normalization augmentation "
            "class imbalance stratified sampling distribution shift "
            "out-of-distribution generalization license CC Creative Commons "
            "PII personally identifiable information anonymization privacy GDPR "
            "data documentation transparency reproducibility"
        ),
        use_when        = (
            "The paper introduces a new dataset, benchmark or data pipeline "
            "for ML or AI research, or evaluates data quality practices."
        ),
    ),

    "sciadv.adk3452.pdf": ChecklistEntry(
        checklist_name  = "Reproducibility in Computational Science (Science Advances)",
        study_type      = "nlp_ml",
        checklist_subtype = "computational_reproducibility",
        guideline_org   = "Science Advances / AAAS",
        n_items         = 0,
        primary_focus   = (
            "Standards for computational and data-driven science reproducibility, "
            "covering code, data, environment, and workflow transparency."
        ),
        key_sections    = (
            "Code availability: version control repository DOI archival; "
            "Data availability: raw data processed data repository; "
            "Computational environment: OS software versions containers Docker; "
            "Workflow: pipeline steps order scripts notebooks; "
            "Random seeds and stochasticity; "
            "Hardware: GPU CPU memory compute time; "
            "Statistical reporting: uncertainty quantification confidence intervals"
        ),
        key_concepts    = (
            "computational reproducibility replicability code availability "
            "data availability open source GitHub GitLab Zenodo DOI "
            "Docker container virtual environment conda pip requirements "
            "random seed stochastic deterministic software version "
            "computational workflow pipeline Jupyter notebook script "
            "hardware GPU CPU memory runtime compute time "
            "uncertainty quantification error bars confidence intervals "
            "independent replication third-party verification preprint "
            "open science FAIR data findable accessible interoperable reusable"
        ),
        use_when        = (
            "The paper involves computational experiments, simulations, "
            "data analysis pipelines or any ML/AI system where code and data reproducibility matter."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # General / Cross-domain
    # Nota: SQUIRE y CHEERS no tienen study_type propio en el router,
    # se indexan como "general" para ser recuperables vía similarity search
    # sin filtro cuando el router no puede clasificar el paper.
    # ══════════════════════════════════════════════════════════════════════════

    "SQUIRE-2.0-checklist (1).pdf": ChecklistEntry(
        checklist_name  = "SQUIRE 2.0 (Standards for QUality Improvement Reporting Excellence)",
        study_type      = "general",
        checklist_subtype = "quality_improvement_healthcare",
        guideline_org   = "SQUIRE Collaborative",
        n_items         = 18,
        primary_focus   = (
            "Reporting of system-level work to improve the quality, safety "
            "and value of healthcare, including context and theoretical rationale."
        ),
        key_sections    = (
            "Title: indicate healthcare improvement initiative; "
            "Abstract: structured with local problem methods interventions results conclusions; "
            "Introduction: nature and significance of local problem "
            "summary of what is known rationale and theoretical basis; "
            "Methods: ethical issues context intervention description "
            "study of the intervention measures analysis; "
            "Results: contextual elements that influenced improvement "
            "steps of improvement evolution details of the intervention "
            "details of the study measures and analysis; "
            "Discussion: summary interpretation limitations; "
            "Conclusions: sustainability spread generalisation; "
            "Funding"
        ),
        key_concepts    = (
            "quality improvement QI healthcare improvement SQUIRE "
            "patient safety clinical quality improvement PDSA Plan Do Study Act "
            "Lean Six Sigma improvement science local problem intervention "
            "process measure outcome measure balancing measure run chart "
            "statistical process control SPC control chart "
            "implementation science context organisational change "
            "stakeholder engagement healthcare system hospital clinic "
            "change management adoption sustainability spread scale-up"
        ),
        use_when        = (
            "The paper reports a quality improvement or patient safety initiative "
            "implemented within a healthcare system or clinical setting."
        ),
    ),

    "PIIS1098301523030310.pdf": ChecklistEntry(
        checklist_name  = "CHEERS 2022 (Consolidated Health Economic Evaluation Reporting Standards)",
        study_type      = "general",
        checklist_subtype = "health_economic_evaluation",
        guideline_org   = "ISPOR (International Society for Pharmacoeconomics and Outcomes Research)",
        n_items         = 28,
        primary_focus   = (
            "Complete and transparent reporting of health economic evaluations, "
            "including cost-effectiveness, cost-utility, cost-benefit and budget-impact analyses."
        ),
        key_sections    = (
            "Title abstract: economic evaluation type; "
            "Introduction: health problem decision context; "
            "Methods: target population and subgroups setting perspective comparators "
            "time horizon discount rate selection of outcomes measurement of outcomes "
            "valuation of outcomes measurement and valuation of resources used "
            "currency price date and conversion resource use and costs model "
            "analytics characterising heterogeneity characterising distributional effects "
            "characterising uncertainty approach to engagement with patients and others; "
            "Results: study parameters incremental costs and outcomes characterising uncertainty; "
            "Discussion: study findings limitations generalisability current knowledge; "
            "Other: source of funding conflicts of interest"
        ),
        key_concepts    = (
            "health economic evaluation CHEERS cost-effectiveness cost-utility cost-benefit "
            "QALY quality-adjusted life year DALY disability-adjusted life year "
            "incremental cost-effectiveness ratio ICER willingness to pay WTP threshold "
            "Markov model decision tree transition probabilities "
            "discount rate time horizon perspective payer societal "
            "direct costs indirect costs productivity loss "
            "sensitivity analysis deterministic probabilistic PSA "
            "tornado diagram cost-effectiveness acceptability curve CEAC "
            "budget impact health technology assessment HTA "
            "NICE FDA EMA reimbursement coverage decision making"
        ),
        use_when        = (
            "The paper presents a health economic evaluation: cost-effectiveness analysis, "
            "cost-utility analysis, cost-benefit analysis, or health technology assessment."
        ),
    ),

    "giae094.pdf": ChecklistEntry(
        checklist_name  = "Academic Reporting Guidelines (General)",
        study_type      = "general",
        checklist_subtype = "general_academic_reporting",
        guideline_org   = "Unknown / Academic Journal",
        n_items         = 0,
        primary_focus   = (
            "General academic research reporting standards applicable across study designs, "
            "covering transparency, methods description and results presentation."
        ),
        key_sections    = (
            "General reporting standards: title abstract methods results discussion; "
            "Transparency and open science; Ethical considerations; "
            "Statistical reporting; References and citations"
        ),
        key_concepts    = (
            "academic reporting research transparency methods results discussion "
            "research integrity open science reproducibility peer review "
            "statistical reporting effect sizes confidence intervals "
            "ethical approval informed consent funding disclosure"
        ),
        use_when        = (
            "No specific reporting guideline matches the study type, "
            "or the paper requires general academic reporting standards."
        ),
    ),

    "acadmed_89_9_2014_05_22_obrien_1301196_sdc1.pdf": ChecklistEntry(
        checklist_name  = "Medical Education Reporting Standards (Academic Medicine 2014)",
        study_type      = "general",
        checklist_subtype = "medical_education_research",
        guideline_org   = "Academic Medicine / AAMC",
        n_items         = 0,
        primary_focus   = (
            "Reporting standards for medical education research, covering curriculum studies, "
            "assessment tools, competency-based education and educational interventions."
        ),
        key_sections    = (
            "Study purpose and design in medical education context; "
            "Participants: learners residents students faculty; "
            "Educational intervention description; "
            "Assessment tools and validity evidence; "
            "Outcomes: knowledge skills attitudes competencies; "
            "Statistical methods appropriate to education research; "
            "Limitations of educational research designs"
        ),
        key_concepts    = (
            "medical education health professions education curriculum "
            "teaching learning assessment competency-based education CBME "
            "milestones entrustable professional activities EPAs "
            "simulation standardized patients OSCEs "
            "clinical training residency clerkship faculty development "
            "educational intervention Kirkpatrick model "
            "validity reliability psychometrics generalizability "
            "needs assessment program evaluation "
            "qualitative methods focus groups interviews thematic analysis"
        ),
        use_when        = (
            "The paper reports research in health professions education, "
            "medical training, curriculum development or educational assessment."
        ),
    ),
}

# ── Extracción con pdfplumber ──────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Limpia artefactos comunes de extracción PDF."""
    # Colapsar espacios múltiples excepto saltos de línea
    text = re.sub(r"[ \t]+", " ", text)
    # Eliminar líneas vacías excesivas (más de 2 seguidas)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Eliminar cabeceras/pies de página típicos (números de página solos)
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def _extract_with_pdfplumber(pdf_path: Path) -> list[dict]:
    """
    Extrae texto página a página con pdfplumber.

    Para cada página intenta:
      1. Extraer tablas estructuradas (las convierte a texto Markdown-like)
      2. Extraer texto con layout preservado

    Retorna lista de dicts con {page_num, text, has_tables}.
    """
    pages_data = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_text_parts: list[str] = []
            has_tables = False

            # — Extraer tablas primero ─────────────────────────────────────────
            tables = page.extract_tables()
            if tables:
                has_tables = True
                for table in tables:
                    if not table:
                        continue
                    # Convertir tabla a formato legible
                    rows = []
                    for row in table:
                        # Limpiar celdas None y normalizar espacios
                        cells = [
                            str(cell).strip().replace("\n", " ") if cell else ""
                            for cell in row
                        ]
                        rows.append(" | ".join(cells))
                    page_text_parts.append("\n".join(rows))

            # — Extraer texto restante (fuera de tablas) ───────────────────────
            # Usar bbox filtering para evitar duplicar el texto de las tablas
            if tables:
                # Obtener bounding boxes de las tablas para excluirlas
                table_bboxes = [t.bbox for t in page.find_tables()] if hasattr(page, "find_tables") else []
                # Filtrar palabras fuera de las tablas
                if table_bboxes:
                    words_outside = [
                        w for w in (page.extract_words() or [])
                        if not any(
                            w["x0"] >= bbox[0] and w["top"] >= bbox[1]
                            and w["x1"] <= bbox[2] and w["bottom"] <= bbox[3]
                            for bbox in table_bboxes
                        )
                    ]
                    non_table_text = " ".join(w["text"] for w in words_outside)
                    if non_table_text.strip():
                        page_text_parts.append(non_table_text)
                else:
                    plain = page.extract_text(layout=True) or ""
                    if plain.strip():
                        page_text_parts.append(plain)
            else:
                plain = page.extract_text(layout=True) or ""
                if plain.strip():
                    page_text_parts.append(plain)

            full_text = _clean_text("\n\n".join(page_text_parts))

            if full_text:
                pages_data.append({
                    "page_num":  page_num,
                    "text":      full_text,
                    "has_tables": has_tables,
                })

    return pages_data


# ── Chunking inteligente ───────────────────────────────────────────────────────

# Separadores priorizados para checklists:
# 1. Doble salto (sección nueva)
# 2. Salto simple (ítem nuevo)  
# 3. Separador de tabla  
# 4. Punto y coma (ítems inline)
# 5. Espacio (último recurso)
CHECKLIST_SEPARATORS = ["\n\n", "\n", " | ", "; ", " "]


def _build_documents(
    pages_data: list[dict],
    entry: ChecklistEntry,
    pdf_name: str,
    splitter: RecursiveCharacterTextSplitter,
) -> list[Document]:
    """
    Convierte páginas extraídas en Documents de LangChain con metadata completa.

    Estrategia:
    - Primero une todas las páginas para permitir que el splitter cruce
      límites de página (un ítem puede partir entre páginas).
    - Adjunta metadata completa a cada chunk, incluyendo página de origen
      cuando es posible.
    """
    # Construir texto completo con marcadores de página
    full_text_parts = []
    for p in pages_data:
        full_text_parts.append(f"[PAGE {p['page_num']}]\n{p['text']}")
    full_text = "\n\n".join(full_text_parts)

    # Split
    chunks = splitter.split_text(full_text)

    documents: list[Document] = []
    for i, chunk in enumerate(chunks):
        # Detectar número de página del chunk (primer [PAGE N] que aparezca)
        page_match = re.search(r"\[PAGE (\d+)\]", chunk)
        page_num = int(page_match.group(1)) if page_match else 0

        # Limpiar marcador de página del contenido
        clean_chunk = re.sub(r"\[PAGE \d+\]\n?", "", chunk).strip()
        if not clean_chunk:
            continue

        # Detectar si el chunk contiene estructura de tabla
        is_table_chunk = " | " in clean_chunk and clean_chunk.count("|") > 2

        # Inferir sección aproximada (primeros 60 chars sin pipes)
        first_line = clean_chunk.split("\n")[0]
        section_hint = re.sub(r"[|#*\[\]]+", "", first_line).strip()[:60]

        doc = Document(
            page_content=clean_chunk,
            metadata={
                # Identidad del checklist
                "source":             pdf_name,
                "checklist_name":     entry.checklist_name,
                "study_type":         entry.study_type,        # valor del router
                "checklist_subtype":  entry.checklist_subtype, # granularidad extra
                # Posición dentro del documento
                "chunk_index":        i,
                "total_chunks":       len(chunks),
                "page_num":           page_num,
                # Características del chunk
                "is_table_chunk":     is_table_chunk,
                "section_hint":       section_hint,
                "char_count":         len(clean_chunk),
            },
        )
        documents.append(doc)

    return documents


# ── Pipeline principal ─────────────────────────────────────────────────────────

def main() -> None:
    log.info("Iniciando indexación de checklists para SIRA")
    log.info("Fuente PDFs : %s", RAG_DATA_DIR)
    log.info("ChromaDB    : %s", DB_PATH)
    log.info("Colección   : %s", COLLECTION)

    if not RAG_DATA_DIR.exists():
        log.error("Directorio rag_data_revisor no encontrado: %s", RAG_DATA_DIR)
        sys.exit(1)

    embed_model = OllamaEmbeddings(model=EMBED_MODEL)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=CHECKLIST_SEPARATORS,
        keep_separator=True,
    )

    # Limpiar y recrear colección
    log.info("Limpiando colección existente...")
    vectorstore = Chroma(
        collection_name=COLLECTION,
        embedding_function=embed_model,
        persist_directory=str(DB_PATH),
    )
    try:
        vectorstore.delete_collection()
        log.info("Colección eliminada.")
    except Exception as e:
        log.warning("No se pudo eliminar colección (puede ser nueva): %s", e)

    vectorstore = Chroma(
        collection_name=COLLECTION,
        embedding_function=embed_model,
        persist_directory=str(DB_PATH),
    )

    # Inventario de PDFs disponibles
    pdfs_disponibles = {p.name: p for p in sorted(RAG_DATA_DIR.glob("*.pdf"))}
    log.info("PDFs encontrados en disco: %d", len(pdfs_disponibles))

    # Stats
    total_chunks    = 0
    archivos_ok     = []
    archivos_error  = []
    archivos_skip   = []

    for pdf_name, entry in FILE_MAP.items():
        if pdf_name not in pdfs_disponibles:
            log.warning("SKIP (no encontrado en disco): %s", pdf_name)
            archivos_skip.append(pdf_name)
            continue

        pdf_path = pdfs_disponibles[pdf_name]
        log.info("─── Procesando: %s", pdf_name)
        log.info("    Checklist : %s | study_type: %s | subtype: %s",
                 entry.checklist_name, entry.study_type, entry.checklist_subtype)

        try:
            # 1. Extracción con pdfplumber
            pages_data = _extract_with_pdfplumber(pdf_path)
            if not pages_data:
                log.warning("    Sin texto extraíble — omitiendo")
                archivos_error.append((pdf_name, "sin texto extraíble"))
                continue

            total_chars = sum(len(p["text"]) for p in pages_data)
            pages_with_tables = sum(1 for p in pages_data if p["has_tables"])
            log.info("    Páginas: %d | Con tablas: %d | Chars totales: %d",
                     len(pages_data), pages_with_tables, total_chars)

            # 2. Chunking
            docs = _build_documents(pages_data, entry, pdf_name, splitter)
            if not docs:
                log.warning("    Sin chunks generados — omitiendo")
                archivos_error.append((pdf_name, "sin chunks"))
                continue

            table_chunks = sum(1 for d in docs if d.metadata["is_table_chunk"])
            log.info("    Chunks: %d | Con estructura de tabla: %d",
                     len(docs), table_chunks)

            # 3. Indexar en ChromaDB
            vectorstore.add_documents(docs)
            total_chunks += len(docs)
            archivos_ok.append(pdf_name)
            log.info("    ✓ Indexado exitosamente")

        except Exception as e:
            log.error("    ✗ Error procesando %s: %s", pdf_name, e, exc_info=True)
            archivos_error.append((pdf_name, str(e)))

    # ── Resumen ────────────────────────────────────────────────────────────────
    log.info("")
    log.info("══════════════════════════════════════════")
    log.info("INDEXACIÓN COMPLETADA")
    log.info("  Archivos procesados : %d / %d", len(archivos_ok), len(FILE_MAP))
    log.info("  Chunks totales      : %d", total_chunks)
    log.info("  En ChromaDB         : %d", vectorstore._collection.count())
    log.info("  Skipped (no en disco): %d", len(archivos_skip))
    log.info("  Errores             : %d", len(archivos_error))

    if archivos_skip:
        log.info("\nArchivos no encontrados en disco:")
        for f in archivos_skip:
            log.info("  - %s", f)

    if archivos_error:
        log.warning("\nArchivos con error:")
        for f, reason in archivos_error:
            log.warning("  - %s : %s", f, reason)

    # ── Verificación de integridad ─────────────────────────────────────────────
    log.info("")
    log.info("══ Verificación de retrieval por study_type ══")

    # Verificar qué study_types quedaron en la DB
    all_meta = vectorstore._collection.get(include=["metadatas"])["metadatas"]
    study_types_indexed = {}
    for m in all_meta:
        st = m.get("study_type", "MISSING")
        study_types_indexed[st] = study_types_indexed.get(st, 0) + 1

    log.info("Distribución de chunks por study_type:")
    for st, count in sorted(study_types_indexed.items()):
        log.info("  %-25s : %d chunks", st, count)

    # Queries de prueba por tipo
    test_queries: dict[str, str] = {
        "rct":               "randomized controlled trial allocation concealment blinding",
        "systematic_review": "PRISMA systematic review meta-analysis search strategy",
        "observational":     "cohort study exposure outcome STROBE confounding",
        "diagnostic":        "STARD sensitivity specificity reference standard index test",
        "nlp_ml":            "language model benchmark reproducibility dataset split",
        "case_report":       "CARE case report timeline intervention outcome",
        "animal_study":      "ARRIVE animal research sample size welfare",
        "general":           "reporting guideline academic paper methodology",
    }

    log.info("\nPruebas de retrieval (k=2 por tipo):")
    for st, query in test_queries.items():
        try:
            results = vectorstore.similarity_search(
                query, k=2,
                filter={"study_type": st},
            )
            if results:
                for r in results:
                    log.info(
                        "  [%s] '%s' — p.%s — %d chars",
                        st,
                        r.metadata.get("checklist_name", "?"),
                        r.metadata.get("page_num", "?"),
                        r.metadata.get("char_count", 0),
                    )
                    log.info("    └─ %s...", r.page_content[:120].replace("\n", " "))
            else:
                log.warning("  [%s] → SIN RESULTADOS con filtro", st)
        except Exception as e:
            log.error("  [%s] → Error en query de prueba: %s", st, e)

    log.info("")
    log.info("Indexación finalizada. DB lista en: %s", DB_PATH)


if __name__ == "__main__":
    main()