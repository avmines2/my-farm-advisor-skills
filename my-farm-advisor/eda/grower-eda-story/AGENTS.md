# Grower EDA Story Local Instructions

- Keep implementation files under this directory and install the entrypoint
  into `${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src/scripts/` at execution time.
- Require an absolute `DATA_PIPELINE_DATA_ROOT`; never read runtime data from
  the checkout or create a repository-local data directory.
- Keep all generated tables, figures, and manifests under the external runtime.
- This reusable subskill does not generate Markdown, HTML, or narrative reports.
- Do not inspect or analyze soil, satellite, or terrain outputs.
- Run `./scripts/validate.sh` from the repository root after structural changes.
