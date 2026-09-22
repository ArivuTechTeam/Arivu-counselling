-- ============================================================================
-- Migration 46 — Seed the global professional-course catalogue
-- Apply after migration-45-global-course-catalog.sql.
-- Expected seed: 12 courses, 34 levels, 175 subjects.
-- ============================================================================

create temporary table catalog_seed_import (
  code text not null,
  level_name text not null,
  subject_name text not null,
  row_order integer not null
) on commit drop;

insert into catalog_seed_import (code, level_name, subject_name, row_order)
select
  split_part(seed_line, '|', 1),
  split_part(seed_line, '|', 2),
  split_part(seed_line, '|', 3),
  seed_order::integer
from regexp_split_to_table(trim($catalog$
CA|Foundation|Accounting
CA|Foundation|Business Economics
CA|Foundation|Business Laws
CA|Foundation|Quantitative Aptitude
CA|Intermediate|Advanced Accounting
CA|Intermediate|Auditing & Ethics
CA|Intermediate|Corporate & Other Laws
CA|Intermediate|Cost & Management Accounting
CA|Intermediate|Financial Management & Strategic Management
CA|Intermediate|Taxation (Income Tax + GST)
CA|Final|Advanced Auditing, Assurance & Ethics
CA|Final|Advanced Financial Management
CA|Final|Direct Tax Laws & International Taxation
CA|Final|Financial Reporting (FR)
CA|Final|Indirect Tax Laws
CA|Final|Integrated Business Solutions (IBS)
CS|CSEET|Business Communication
CS|CSEET|Current Affairs and Quantitative Aptitude
CS|CSEET|Economic & Business Environment
CS|CSEET|Legal Aptitude and Logical Reasoning
CS|Executive|Capital Market and Securities Laws
CS|Executive|Company Law and Practice
CS|Executive|Corporate Accounting and Financial Management
CS|Executive|Economic, Commercial and Intellectual Property Laws
CS|Executive|Jurisprudence, Interpretation and General Laws
CS|Executive|Setting Up of Business, Industrial and Labour Laws
CS|Executive|Tax Laws and Practice
CS|Professional|Compliance Management, Audit and Due Diligence
CS|Professional|Corporate Restructuring, Valuation and Insolvency
CS|Professional|Drafting, Pleading and Appearances
CS|Professional|Elective 1
CS|Professional|Elective 2
CS|Professional|Environmental, Social and Governance – Principles and Practice
CS|Professional|Strategic Management and Corporate Finance
CMA|Foundation|Fundamentals of Business Economics & Management
CMA|Foundation|Fundamentals of Business Laws & Business Communication
CMA|Foundation|Fundamentals of Business Mathematics & Statistics
CMA|Foundation|Fundamentals of Financial and Cost Accounting
CMA|Intermediate|Business Laws & Ethics
CMA|Intermediate|Corporate Accounting & Auditing
CMA|Intermediate|Cost Accounting
CMA|Intermediate|Direct and Indirect Taxation
CMA|Intermediate|Financial Accounting
CMA|Intermediate|Financial Management & Business Data Analytics
CMA|Intermediate|Management Accounting
CMA|Intermediate|Operations Management & Strategic Management
CMA|Final|Corporate & Economic Laws
CMA|Final|Corporate Financial Reporting
CMA|Final|Cost & Management Audit
CMA|Final|Direct Tax Laws & International Taxation
CMA|Final|Elective Paper (Strategic Performance Management & Business Valuation)
CMA|Final|Indirect Tax Laws & Practice
CMA|Final|Strategic Cost Management
CMA|Final|Strategic Financial Management
ACCA|Applied Knowledge|Business and Technology (BT)
ACCA|Applied Knowledge|Financial Accounting (FA)
ACCA|Applied Knowledge|Management Accounting (MA)
ACCA|Applied Skills|Audit and Assurance (AA)
ACCA|Applied Skills|Corporate and Business Law (LW)
ACCA|Applied Skills|Financial Management (FM)
ACCA|Applied Skills|Financial Reporting (FR)
ACCA|Applied Skills|Performance Management (PM)
ACCA|Applied Skills|Taxation (TX)
ACCA|Strategic Professional|Advanced Audit and Assurance (AAA)
ACCA|Strategic Professional|Advanced Financial Management (AFM)
ACCA|Strategic Professional|Advanced Performance Management (APM)
ACCA|Strategic Professional|Advanced Taxation (ATX)
ACCA|Strategic Professional|Strategic Business Leader (SBL)
ACCA|Strategic Professional|Strategic Business Reporting (SBR)
CIMA|Certificate|Fundamentals of Business Economics
CIMA|Certificate|Fundamentals of Ethics, Corporate Governance & Business Law
CIMA|Certificate|Fundamentals of Financial Accounting
CIMA|Certificate|Fundamentals of Management Accounting
CIMA|Operational|Financial Reporting
CIMA|Operational|Management Accounting
CIMA|Operational|Managing Finance in a Digital World
CIMA|Operational|Operational Case Study Exam
CIMA|Management|Advanced Financial Reporting
CIMA|Management|Advanced Management Accounting
CIMA|Management|Management Case Study Exam
CIMA|Management|Managing Performance
CIMA|Strategic|Financial Strategy
CIMA|Strategic|Risk Management
CIMA|Strategic|Strategic Case Study Exam
CIMA|Strategic|Strategic Management
CMA_USA|Part 1|Cost management
CMA_USA|Part 1|External financial reporting decisions
CMA_USA|Part 1|Internal Control
CMA_USA|Part 1|Performance management
CMA_USA|Part 1|Planning, budgeting & forecasting
CMA_USA|Part 1|Technology & Analytics
CMA_USA|Part 2|Corporate finance
CMA_USA|Part 2|Decision analysis
CMA_USA|Part 2|Financial Statement Analysis
CMA_USA|Part 2|Investment Decisions
CMA_USA|Part 2|Professional Ethics
CMA_USA|Part 2|Risk management
CIA|Part 1|Foundations of Internal Auditing
CIA|Part 1|Fraud Risks
CIA|Part 1|Governance, Risk Management & Control
CIA|Part 1|Independence & Objectivity
CIA|Part 1|Proficiency & Due Professional Care
CIA|Part 1|Quality Assurance & Improvement Programs
CIA|Part 2|Communicating Engagement Results & Monitoring
CIA|Part 2|Managing the Internal Audit Activity
CIA|Part 2|Performing the Audit Engagement
CIA|Part 2|Planning the Audit Engagement
CIA|Part 3|Business Acumen
CIA|Part 3|Financial Management
CIA|Part 3|Information Security
CIA|Part 3|Information Technology
EA|Part 1|Advising the individual taxpayer
EA|Part 1|Deductions and credits
EA|Part 1|Income and assets
EA|Part 1|Preliminary Work and Taxpayer Data
EA|Part 1|Specialized returns for individuals
EA|Part 1|Taxation
EA|Part 2|Business Entities and Considerations
EA|Part 2|Business Tax Preparation
EA|Part 2|Specialised Returns and Taxpayers
EA|Part 3|Filing Process
EA|Part 3|Practices and procedures
EA|Part 3|Representation before the IRS
EA|Part 3|Specific types of representation (audits, collections, appeals)
FRM|Part 1|Financial Markets and Products
FRM|Part 1|Foundations of Risk Management
FRM|Part 1|Quantitative Analysis
FRM|Part 1|Valuation and Risk Models
FRM|Part 2|Credit Risk Measurement and Management
FRM|Part 2|Current Issues in Financial Markets
FRM|Part 2|Liquidity and Treasury Risk Management
FRM|Part 2|Market Risk Measurement and Management
FRM|Part 2|Operational Risk and Resilience
FRM|Part 2|Risk Management and Investment Management
CFA|Level 1|Alternative Investments
CFA|Level 1|Corporate Issuers
CFA|Level 1|Derivatives
CFA|Level 1|Economics
CFA|Level 1|Equity Investments
CFA|Level 1|Ethical and Professional Standards
CFA|Level 1|Financial Statement Analysis
CFA|Level 1|Fixed Income
CFA|Level 1|Portfolio Management & Wealth Planning
CFA|Level 1|Quantitative Methods
CFA|Level 2|Alternative Investments
CFA|Level 2|Corporate Issuers
CFA|Level 2|Derivatives
CFA|Level 2|Economics
CFA|Level 2|Equity Valuation
CFA|Level 2|Ethical and Professional Standards
CFA|Level 2|Financial Reporting and Analysis
CFA|Level 2|Fixed Income
CFA|Level 2|Portfolio Management
CFA|Level 2|Quantitative Methods
CFA|Level 3|Asset Allocation
CFA|Level 3|Derivatives and Risk Management
CFA|Level 3|Ethical and Professional Standards
CFA|Level 3|Pathways: Portfolio Mgmt / Private Markets / Private Wealth
CFA|Level 3|Performance Measurement
CFA|Level 3|Portfolio Construction
CPA_US|Core Sections|Auditing and Attestation (AUD)
CPA_US|Core Sections|Business Analysis (BAR)
CPA_US|Core Sections|Financial Accounting and Reporting (FAR)
CPA_US|Core Sections|Information Systems Control (ISC)
CPA_US|Core Sections|Tax Compliance and Planning (TCP)
CPA_US|Core Sections|Taxation and Regulation (REG)
CFP|Level 1|Investment Planning and Asset Management
CFP|Level 1|Personal Financial Management
CFP|Level 1|Regulatory Environment, Law and Compliance
CFP|Level 2|Retirement Planning
CFP|Level 2|Tax Planning and Optimization
CFP|Level 3|Estate Planning
CFP|Level 3|Risk Management and Insurance Planning
CFP|Level 4|Financial Planning Principles, Process & Skills
CFP|Level 4|Integrated Financial Planning
$catalog$), E'\n') with ordinality as seeded(seed_line, seed_order)
where seed_line <> '';

with first_course_row as (
  select code, min(row_order) as first_order
  from catalog_seed_import
  group by code
), ordered_courses as (
  select
    code,
    row_number() over (order by first_order) - 1 as display_order
  from first_course_row
)
insert into public.catalog_courses (code, name, display_order)
select
  code,
  case code
    when 'CA' then 'Chartered Accountant'
    when 'CS' then 'Company Secretary'
    when 'CMA' then 'Cost & Management Accountant'
    when 'ACCA' then 'Association of Chartered Certified Accountants'
    when 'CIMA' then 'Chartered Institute of Management Accountants'
    when 'CMA_USA' then 'Certified Management Accountant (US)'
    when 'CIA' then 'Certified Internal Auditor'
    when 'EA' then 'Enrolled Agent'
    when 'FRM' then 'Financial Risk Manager'
    when 'CFA' then 'Chartered Financial Analyst'
    when 'CPA_US' then 'Certified Public Accountant (US)'
    when 'CFP' then 'Certified Financial Planner'
  end,
  display_order
from ordered_courses
on conflict (code) do nothing;

with first_level_row as (
  select code, level_name, min(row_order) as first_order
  from catalog_seed_import
  group by code, level_name
), ordered_levels as (
  select
    code,
    level_name,
    row_number() over (partition by code order by first_order) - 1 as display_order
  from first_level_row
)
insert into public.catalog_course_levels (
  catalog_course_id,
  name,
  display_order
)
select cc.id, levels.level_name, levels.display_order
from ordered_levels levels
join public.catalog_courses cc on cc.code = levels.code
on conflict (catalog_course_id, name) do nothing;

insert into public.catalog_course_subjects (catalog_level_id, name)
select cl.id, seed.subject_name
from catalog_seed_import seed
join public.catalog_courses cc on cc.code = seed.code
join public.catalog_course_levels cl
  on cl.catalog_course_id = cc.id and cl.name = seed.level_name
order by seed.row_order
on conflict (catalog_level_id, name) do nothing;

do $$
declare
  seeded_courses integer;
  seeded_levels integer;
  seeded_subjects integer;
begin
  select count(distinct cc.id)
  into seeded_courses
  from catalog_seed_import seed
  join public.catalog_courses cc on cc.code = seed.code;

  select count(distinct cl.id)
  into seeded_levels
  from catalog_seed_import seed
  join public.catalog_courses cc on cc.code = seed.code
  join public.catalog_course_levels cl
    on cl.catalog_course_id = cc.id and cl.name = seed.level_name;

  select count(distinct cs.id)
  into seeded_subjects
  from catalog_seed_import seed
  join public.catalog_courses cc on cc.code = seed.code
  join public.catalog_course_levels cl
    on cl.catalog_course_id = cc.id and cl.name = seed.level_name
  join public.catalog_course_subjects cs
    on cs.catalog_level_id = cl.id and cs.name = seed.subject_name;

  if seeded_courses <> 12 or seeded_levels <> 34 or seeded_subjects <> 175 then
    raise exception
      'Catalog seed verification failed: expected 12/34/175, found %/%/%',
      seeded_courses, seeded_levels, seeded_subjects;
  end if;
end;
$$;

-- ============================================================================
-- END OF MIGRATION 46
-- ============================================================================
