# Kriton Authoritative Sources Catalog

**Status:** Working source-integration register  
**Last reviewed:** 1 August 2026  
**Scope:** Accounting, audit, tax, law, regulation, compliance, corporate data, economic data, sanctions, and procurement

This catalog records the official and authoritative sources Kriton may use, their intended integration method, access model, implementation status, and official URL. Free access does not automatically grant permission to reproduce, redistribute, train on, or export complete source content.

## Legend

| Code | Meaning |
|---|---|
| `LIVE_API` | Query an official API for current structured data. |
| `SCHEDULED_FEED` | Periodically synchronize official XML, CSV, JSON, RSS, or bulk data. |
| `VERSIONED_DOC` | Ingest official documents with publication, effective, and superseded dates. |
| `LICENSED_DOC` | Ingest only with the required subscription or commercial licence. |
| `DISCOVERY_ONLY` | Locate evidence but do not treat the source as controlling authority. |
| Free | No API charge; terms, attribution, and rate limits can still apply. |
| Restricted | OAuth, consent, approval, certification, or provider authorization is required. |
| Mixed | Some access is free while enhanced access, documents, or reuse is paid. |

## Current Kriton baseline

Implemented integrations include World Bank, ONS, Bank of England, Frankfurter FX, FRED, SEC EDGAR, Companies House, OECD, GLEIF, US Treasury Fiscal Data, Census, BLS, BEA, GovInfo, eCFR, Federal Register, and Congress.gov, plus the Phase 1-3 additions registered below (ECB, IMF, VIES, Regulations.gov, Cellar, legislation.gov.uk, TED, SAM.gov, and the four sanctions feeds). IRS, FASB, PCAOB, SEC filing retrieval, Companies House documents, and US tax-regulation coverage are partial.

Two coverage limits are deliberate rather than pending. IMF routing resolves only the countries with a confirmed ISO3 mapping (GB, US, IN), and OECD only those confirmed against its corporate-tax dataflow: a country is added once a real query proves the upstream holds data for it, never by constructing a plausible code and citing whatever comes back. Naming the IMF in a query selects it over the domestic provider for that country; a query that does not name it keeps its domestic source.

## 1. Accounting standards

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| IFRS Foundation / IASB | `LICENSED_DOC` | Basic registration free; commercial integration/licensing paid | Not fully implemented | [Standards](https://www.ifrs.org/issued-standards/list-of-standards/), [licensing](https://www.ifrs.org/use-around-the-world/adoption-and-copyright/) |
| FASB Codification | `LICENSED_DOC` | Basic View free; Professional View and commercial use paid/licensed | Partial | [FASB Standards](https://fasb.org/standards), [access](https://fasb.org/page/PageContent?isStaticPage=true&pageId=%2Fstaticpages%2Fcodification-access.html) |
| ICAI Accounting Standards | `VERSIONED_DOC` | Public/member content; reuse review required | Not implemented | [ICAI](https://www.icai.org/) |
| IPSASB | `VERSIONED_DOC` | Generally free to access; copyright terms apply | Not implemented | [IPSASB](https://www.ipsasb.org/publications) |

## 2. Auditing standards

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| IAASB / ISA | `VERSIONED_DOC` | Generally free to access; reproduction terms apply | Not implemented | [IAASB](https://www.iaasb.org/publications) |
| PCAOB | `VERSIONED_DOC` | Free | Partial | [PCAOB standards](https://pcaobus.org/oversight/standards/auditing-standards) |
| ICAI Auditing Standards | `VERSIONED_DOC` | Public/member content; reuse review required | Not implemented | [ICAI](https://www.icai.org/) |
| IFAC | `VERSIONED_DOC` | Free/mixed; copyright permissions apply | Not implemented | [IFAC](https://www.ifac.org/knowledge-gateway) |

## 3. Tax

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| IRS | `VERSIONED_DOC` plus supported official data services | Free | Partial | [IRS](https://www.irs.gov/) |
| HMRC | `LIVE_API` plus `VERSIONED_DOC` | Free registration; OAuth, consent, and production approval required | Not implemented | [HMRC Developer Hub](https://developer.service.hmrc.gov.uk/api-documentation) |
| OECD Tax Data | `LIVE_API` with caching | Free under terms; rate limited | Partial | [OECD API](https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html) |
| CBDT | `VERSIONED_DOC` | Free | Not implemented | [Income Tax India](https://incometaxindia.gov.in/) |
| CBIC | `VERSIONED_DOC` | Free | Not implemented | [CBIC Tax Information](https://taxinformation.cbic.gov.in/) |
| GST Council | `VERSIONED_DOC` | Free | Not implemented | [GST Council](https://gstcouncil.gov.in/) |
| GSTN | `LIVE_API` | Restricted; approved-provider and taxpayer authorization required | Not implemented | [GSTN](https://www.gstn.org.in/) |
| European Commission TAXUD | `LIVE_API` plus `VERSIONED_DOC` | Mixed by service | Not implemented | [TAXUD](https://taxation-customs.ec.europa.eu/) |
| VIES | `LIVE_API` | Generally free | Not implemented | [VIES](https://ec.europa.eu/taxation_customs/vies/) |

## 4. Corporate registries

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| SEC EDGAR | `LIVE_API` | Free; user agent and fair-access compliance required | Implemented/partial expansion | [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Companies House | `LIVE_API` | Free API key; rate limited | Implemented/partial documents | [Companies House API](https://developer.company-information.service.gov.uk/get-started) |
| MCA | Authorized integration plus `VERSIONED_DOC` | Mixed; some documents/products paid | Not implemented | [MCA](https://www.mca.gov.in/) |
| GLEIF | `LIVE_API` | Free | Implemented | [GLEIF API](https://www.gleif.org/en/lei-data/gleif-api/) |
| ASIC | Restricted API plus documents | Provider approval required; some extracts paid | Not implemented | [ASIC APIs](https://www.asic.gov.au/online-services/information-for-intermediaries/application-programming-interfaces-apis/) |
| OpenCorporates | `DISCOVERY_ONLY` | Commercial/paid | Not implemented; not controlling | [OpenCorporates API](https://knowledge.opencorporates.com/knowledge-base/api-documentation/) |

## 5. Financial reporting

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| SEC XBRL | `LIVE_API` | Free under fair-access rules | Partial | [SEC XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Companies House filings | `LIVE_API` plus governed document retrieval | Free/mixed restrictions | Partial | [Companies House](https://developer.company-information.service.gov.uk/) |
| MCA filings | Restricted retrieval plus `VERSIONED_DOC` | Mixed/paid | Not implemented | [MCA](https://www.mca.gov.in/) |
| XBRL International | `VERSIONED_DOC` or open-data service | Generally free; not a statutory filing authority | Not implemented | [XBRL International](https://www.xbrl.org/) |

## 6. Corporate governance

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| OECD Corporate Governance | `VERSIONED_DOC` | Free/mixed reuse terms | Not implemented | [OECD](https://www.oecd.org/en/topics/corporate-governance.html) |
| SEC | `LIVE_API` plus `VERSIONED_DOC` | Free | Partial | [SEC](https://www.sec.gov/) |
| FCA | `VERSIONED_DOC` plus register integration | Public/mixed | Not implemented | [Handbook](https://handbook.fca.org.uk/), [Register](https://register.fca.org.uk/) |
| SEBI | `VERSIONED_DOC` | Free | Not implemented | [SEBI](https://www.sebi.gov.in/) |
| ASIC | Restricted API plus `VERSIONED_DOC` | Mixed | Not implemented | [ASIC](https://www.asic.gov.au/) |

## 7. Company identifiers

| Source | Identifier | Integration | Access | Status | Official URL |
|---|---|---|---|---|---|
| GLEIF | LEI and mapped identifiers | `LIVE_API` | Free | Implemented | [GLEIF](https://www.gleif.org/en/lei-data/gleif-api/) |
| Dun & Bradstreet | DUNS | Commercial API | Paid | Not implemented | [D&B Developer](https://docs.dnb.com/) |
| ANNA / numbering agencies | ISIN | Licensed dataset/API | Mixed/paid | Not implemented | [ANNA](https://www.anna-web.org/) |
| SEC | CIK | `LIVE_API` | Free | Implemented | [SEC EDGAR](https://www.sec.gov/edgar) |
| Companies House | UK company number | `LIVE_API` | Free API key | Implemented | [Companies House](https://developer.company-information.service.gov.uk/) |
| MCA | CIN/LLPIN | Registry integration | Mixed | Not implemented | [MCA](https://www.mca.gov.in/) |

## 8. Laws and legislation

| Source | Jurisdiction | Integration | Access | Status | Official URL |
|---|---|---|---|---|---|
| GovInfo | US | `LIVE_API` plus official documents | Free API key | Implemented | [GovInfo](https://www.govinfo.gov/developers) |
| Congress.gov | US | `LIVE_API` | Free API key | Implemented | [Congress API](https://api.congress.gov/) |
| Federal Register | US | `LIVE_API` discovery | Free, no key | Implemented | [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1) |
| eCFR | US | `LIVE_API` | Free | Implemented | [eCFR](https://www.ecfr.gov/developers/documentation/api/v1) |
| legislation.gov.uk | UK | Machine-readable feed/API plus `VERSIONED_DOC` | Free | Not implemented | [UK Legislation](https://www.legislation.gov.uk/) |
| EUR-Lex / Cellar | EU | Search service, REST retrieval, and bulk data | Free registration/public reuse terms | Not implemented | [EUR-Lex service](https://eur-lex.europa.eu/content/help/data-reuse/webservice.html?locale=en) |
| India Code | India | `VERSIONED_DOC` | Free | Not implemented | [India Code](https://www.indiacode.nic.in/) |

FederalRegister.gov should be used for discovery; controlling US legal citations should resolve to the corresponding official GovInfo edition when available.

## 9. Case law

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| Supreme Court of India | `VERSIONED_DOC` | Free | Not implemented | [Supreme Court](https://www.sci.gov.in/) |
| eCourts | Official search/document integration | Free portal; no assumed general API | Not implemented | [eCourts](https://ecourts.gov.in/) |
| CURIA / EUR-Lex | Search service plus `VERSIONED_DOC` | Free/registration | Not implemented | [CURIA](https://curia.europa.eu/), [EUR-Lex](https://eur-lex.europa.eu/) |
| BAILII | `DISCOVERY_ONLY` plus permitted documents | Free; reuse terms apply | Not implemented | [BAILII](https://www.bailii.org/) |
| CourtListener | `DISCOVERY_ONLY` API | Generally free registration | Not implemented | [CourtListener](https://www.courtlistener.com/help/) |

## 10. Financial regulations

| Source | Jurisdiction | Integration | Access | Status | Official URL |
|---|---|---|---|---|---|
| SEC | US | API plus `VERSIONED_DOC` | Free | Partial | [SEC](https://www.sec.gov/) |
| FCA | UK | Handbook and register integration | Public/mixed | Not implemented | [FCA](https://www.fca.org.uk/) |
| SEBI | India | `VERSIONED_DOC` | Free | Not implemented | [SEBI](https://www.sebi.gov.in/) |
| RBI | India | `VERSIONED_DOC` plus supported datasets | Free | Not implemented | [RBI](https://www.rbi.org.in/) |
| ESMA | EU | Registers, datasets, and `VERSIONED_DOC` | Mostly free/service-specific | Not implemented | [ESMA data](https://www.esma.europa.eu/databases-library/registers-and-data) |
| ASIC | Australia | Restricted API plus documents | Mixed | Not implemented | [ASIC](https://www.asic.gov.au/) |
| MAS | Singapore | Supported APIs/datasets plus documents | Mostly free/service-specific | Not implemented | [MAS](https://www.mas.gov.sg/) |
| Regulations.gov | US | `LIVE_API` | Free API key | Implemented (search + answer adapters) | [Regulations.gov API](https://open.gsa.gov/api/regulationsgov/) |

## 11. Accounting guidance

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| IFRS educational material | `LICENSED_DOC`/`VERSIONED_DOC` | Mixed; commercial permission may be required | Not implemented | [IFRS projects](https://www.ifrs.org/projects/work-plan/) |
| FASB implementation material | `LICENSED_DOC` | Basic free; professional/licensed content paid | Partial | [FASB](https://fasb.org/) |
| ICAI Guidance Notes | `VERSIONED_DOC` | Public/mixed; reuse review required | Not implemented | [ICAI](https://www.icai.org/) |
| PCAOB staff guidance | `VERSIONED_DOC` | Free | Partial | [PCAOB](https://pcaobus.org/oversight/standards) |

## 12. Tax treaties

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| OECD treaty material | `LICENSED_DOC`/`VERSIONED_DOC` | Mixed; books/premium content may be paid | Not implemented | [OECD Tax Treaties](https://www.oecd.org/en/topics/tax-treaties.html) |
| UN Model Convention | `VERSIONED_DOC` | Public; reuse terms apply | Not implemented | [UN Tax Committee](https://financing.desa.un.org/what-we-do/ECOSOC/tax-committee/thematic-areas/tax-treaties) |
| National treaty collections | `VERSIONED_DOC` | Usually free official publication | Not implemented broadly | Relevant national authority |
| EUR-Lex treaties | Search service plus `VERSIONED_DOC` | Free registration | Not implemented | [EUR-Lex](https://eur-lex.europa.eu/) |

Binding answers must prioritize the ratified treaty text over model conventions and commentary.

## 13. Transfer pricing

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| OECD Transfer Pricing Guidelines | `LICENSED_DOC`/`VERSIONED_DOC` | Mixed; some publications paid/licensed | Not implemented | [OECD](https://www.oecd.org/en/topics/transfer-pricing.html) |
| CBDT rules | `VERSIONED_DOC` | Free | Not implemented | [Income Tax India](https://incometaxindia.gov.in/) |
| IRS guidance | `VERSIONED_DOC` | Free | Partial | [IRS Transfer Pricing](https://www.irs.gov/businesses/international-businesses/transfer-pricing) |
| HMRC International Manual | `VERSIONED_DOC` | Free | Not implemented | [HMRC Manuals](https://www.gov.uk/government/collections/hmrc-manuals) |

## 14. AML and compliance

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| FATF | `VERSIONED_DOC` plus monitored-list sync | Free; reuse terms apply | Not implemented | [FATF Recommendations](https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations.html) |
| FinCEN | `VERSIONED_DOC` plus supported official datasets | Free | Not implemented | [FinCEN](https://www.fincen.gov/) |
| FIU-IND | `VERSIONED_DOC` plus restricted reporting integration | Public guidance; operational access restricted | Not implemented | [FIU-IND](https://fiuindia.gov.in/) |
| FCA financial-crime guidance | `VERSIONED_DOC` | Free | Not implemented | [FCA](https://www.fca.org.uk/firms/financial-crime) |
| RBI KYC/AML directions | `VERSIONED_DOC` | Free | Not implemented | [RBI](https://www.rbi.org.in/) |

## 15. Sanctions and financial crime

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| OFAC | `LIVE_API` plus `SCHEDULED_FEED` | Free | Not implemented | [OFAC SLS](https://ofac.treasury.gov/other-ofac-sanctions-lists) |
| UN Security Council | `SCHEDULED_FEED` XML | Free | Not implemented | [UN list](https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list) |
| UK Sanctions List | `SCHEDULED_FEED` XML/CSV | Free | Not implemented | [UK list](https://www.gov.uk/government/publications/the-uk-sanctions-list) |
| EU sanctions | `SCHEDULED_FEED` | Free | Not implemented | [EU Sanctions Map](https://www.sanctionsmap.eu/) |
| FinCEN advisories | `VERSIONED_DOC` | Free | Not implemented | [FinCEN advisories](https://www.fincen.gov/resources/advisoriesbulletinsfact-sheets) |

Sanctions screening must record the list version, update timestamp, matching method, identifiers, and source URL. Possible matches require review and must not automatically become adverse decisions.

Implemented as follows. Every screening result carries the list version (`SanctionsSnapshot.list_version`, the first 12 characters of the content hash — the only identifier these authorities publish that changes when and only when the list does), the synchronisation timestamp, the matching method, and the identifiers held on the matched entry.

Matching runs in three tiers, strongest first:

1. **Identifier** — passport, national ID, or registration number, compared on alphanumerics only so `P1234567`, `p 1234 567` and `P-1234567` all reach the same listing. Reported **even when the name does not match**: a number identifies a party where a name only describes one, and suppressing that because a transliteration differs would discard the strongest signal the list carries. Identifiers below five characters are ignored — too generic to assert identity.
2. **Exact name**, on the normalised primary name or any published alias.
3. **Fuzzy name**, above `SANCTIONS_FUZZY_MATCH_THRESHOLD`, narrowed by shared token so the comparison stays bounded on lists of tens of thousands of entries.

Identifiers are extracted from a query only behind an explicit label (`passport P1234567`, `registration number 7788990`); an unlabelled number in a sentence is never screened as one, because a false identifier match is the most damaging result this path can produce.

The record states what was compared, not only what was found — a name-only screen and a name-plus-passport screen carry very different weight, and an unqualified "no match" implies the stronger one. Where an entry publishes no identifier, the result says so rather than omitting the field. No result is ever phrased as a finding or as clearance.

## 16. Economic and financial indicators

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| IMF | `LIVE_API` with SDMX caching | Generally free; some portal functions require registration | Not implemented | [IMF API](https://data.imf.org/en/Resource-Pages/IMF-API) |
| World Bank | `LIVE_API` | Free, no key | Implemented | [World Bank API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392) |
| OECD | `LIVE_API` | Free; rate limited | Partial | [OECD API](https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html) |
| FRED | `LIVE_API` | Free API key; attribution/source terms apply | Implemented | [FRED API](https://fred.stlouisfed.org/docs/api/fred/overview.html) |
| ECB Data Portal | Direct SDMX API | Free | Not directly implemented | [ECB API](https://data.ecb.europa.eu/help/api/overview) |
| Bank of England | `LIVE_API`/database service | Free | Implemented | [BoE Database](https://www.bankofengland.co.uk/boeapps/database/) |
| ONS | `LIVE_API` | Free | Implemented | [ONS API](https://developer.ons.gov.uk/) |
| BEA | `LIVE_API` | Free API key | Implemented | [BEA API](https://apps.bea.gov/api/signup/) |
| BLS | `LIVE_API` | Free; registration raises limits | Implemented | [BLS API](https://www.bls.gov/developers/) |

## 17. Banking regulations

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| Basel Committee / BCBS | `VERSIONED_DOC` | Free | Not implemented | [BCBS](https://www.bis.org/bcbs/) |
| RBI | `VERSIONED_DOC` plus supported data | Free | Not implemented | [RBI](https://www.rbi.org.in/) |
| Federal Reserve | `VERSIONED_DOC` plus financial data | Free | FRED covered; regulations partial | [Federal Reserve](https://www.federalreserve.gov/) |
| ECB Banking Supervision | `VERSIONED_DOC` plus ECB API | Free | Not implemented | [ECB Supervision](https://www.bankingsupervision.europa.eu/) |
| Bank of England / PRA | `VERSIONED_DOC` | Free | Data covered; prudential rules missing | [PRA](https://www.bankofengland.co.uk/prudential-regulation) |
| MAS | `VERSIONED_DOC` plus supported datasets | Free/mixed | Not implemented | [MAS](https://www.mas.gov.sg/) |

## 18. Professional bodies

Professional-body guidance does not override legislation, regulators, courts, or standard setters.

| Source | Integration | Access | Status | Official URL |
|---|---|---|---|---|
| IFAC | `VERSIONED_DOC` | Free/mixed | Not implemented | [IFAC](https://www.ifac.org/) |
| ICAEW | `VERSIONED_DOC` | Mixed/membership | Not implemented | [ICAEW](https://www.icaew.com/) |
| ACCA | `VERSIONED_DOC` | Public/membership | Not implemented | [ACCA](https://www.accaglobal.com/) |
| CPA Australia | `VERSIONED_DOC` | Public/membership | Not implemented | [CPA Australia](https://www.cpaaustralia.com.au/) |
| AICPA | `VERSIONED_DOC`/licensed content | Mixed/paid | Not implemented | [AICPA-CIMA](https://www.aicpa-cima.com/) |
| ICAI | `VERSIONED_DOC` | Public/member | Not implemented | [ICAI](https://www.icai.org/) |

## 19. Public procurement and government finance

| Source | Jurisdiction | Integration | Access | Status | Official URL |
|---|---|---|---|---|---|
| TED | EU | `LIVE_API` | Free for published notices | Not implemented | [TED API](https://docs.ted.europa.eu/api/latest/search.html) |
| SAM.gov | US | `LIVE_API` | Free API key | Not implemented | [GSA APIs](https://open.gsa.gov/api/) |
| Contracts Finder | UK | `LIVE_API` | Public retrieval free; publishing restricted | Not implemented | [Contracts Finder API](https://www.contractsfinder.service.gov.uk/apidocumentation/home) |
| Find a Tender | UK | Feed/API integration | Free public notices | Not implemented | [Find a Tender](https://www.find-tender.service.gov.uk/) |
| CPPP | India | Portal/document sync | Free search; no assumed stable API | Not implemented | [CPPP](https://eprocure.gov.in/eprocure/app) |
| GeM | India | Restricted official integration | Public portal; transactions restricted | Not implemented | [GeM](https://gem.gov.in/) |
| World Bank Procurement | International | Feed/API/documents | Free | Not implemented | [World Bank](https://www.worldbank.org/en/projects-operations/products-and-services/procurement-projects-programs) |
| UNGM | UN | Feed/registered integration | Basic access generally free; enhanced services vary | Not implemented | [UNGM](https://www.ungm.org/) |
| US Treasury Fiscal Data | US | `LIVE_API` | Free | Implemented | [Fiscal Data API](https://fiscaldata.treasury.gov/api-documentation/) |

## Required source metadata

Recorded on `live_source_providers` (`app/domains/live_sources/models.py`) and populated by `scripts/seed_live_source_provider.py`, which is re-runnable: an existing row has its catalogue metadata refreshed in place, so correcting a rank or a licence URL is a re-run rather than a manual `UPDATE`.

| Catalogue field | Column |
|---|---|
| `source_id` | `provider_key` |
| `authority_name` | `display_name` |
| `authority_rank` | `authority_rank` (1-6, see hierarchy below) |
| `jurisdiction` | `jurisdiction` |
| `domain` | `category` |
| `integration_type` | `integration_type` |
| `official_url` | `official_url` |
| `api_base_url` | `base_url` |
| `authentication_type` | `auth_mode` (+ `api_key_env_var`, never the key itself) |
| `pricing_model` | `pricing_model` |
| `licence_terms_url` | `licence_terms_url` |
| `publication_date` / `effective_date` / `superseded_date` | `effective_date` / `superseded_date` — at provider level these mean when the integration became and ceased authoritative. Document-level dates belong to the retrieved record, not the registry row. |
| `last_successful_sync` | `last_successful_sync` (written by the sanctions sync task) |
| `freshness_sla` | `freshness_sla_seconds` — enforced at answer time: a figure older than its source's own SLA is labelled NOT CURRENT in the model's context and qualified in the citation title, because a failed live fetch falls back to a stale cache entry and otherwise presents it as current |
| `content_hash` | `last_content_hash` |
| `display_permission` | `display_permission` (empty = derive from the licence gate). Honoured at Checkpoint B, and can only ever tighten: a row asking for `show` on a source whose licence is unknown is still held at `internal_reasoning_only`, because a licence state is a legal fact and a display preference is not permission to override it |
| `export_permission` | `export_permission` |
| `tenant_entitlement` | `tenant_id` + `is_tenant_private` |

The table is created by `Base.metadata.create_all`, not by an Alembic revision, and `create_all` never alters an existing table. Adding a column therefore also needs an entry in `app/domains/live_sources/schema_sync.py`, which both the API's startup and the test suite apply.

## Default authority hierarchy

1. Enacted legislation, official regulations, and binding court decisions
2. Applicable regulator, tax authority, or accounting/auditing standard setter
3. Official company registry or government filing system
4. Official international organization
5. Recognized professional-body guidance
6. Commercial or secondary discovery source

The hierarchy must also account for jurisdiction, effective date, entity type, reporting framework, and the exact query. International models and professional guidance must not override binding domestic implementation.

Implemented in `app/domains/live_sources/authority.py` and applied when a bundle decides which citation is `controlling`. Jurisdiction is applied **before** rank, so a rank-1 foreign statute cannot outrank the rank-2 domestic regulator that actually governs the answer, and an international model cannot displace a domestic source on that source's own jurisdiction. Effective date breaks ties between equals, so a superseded instrument of identical standing is not treated as controlling. A source with no recorded rank defaults to the weakest, not the neutral, position — an unranked source must never displace one whose standing is known. Where nothing in a bundle carries a rank (the normal case for ingested documents), retrieval order is retained, so this changes behaviour only where authority is actually known.

Ranks reach both kinds of source. A live provider's rank is read from its registry row; a governed document's is derived by the licence gate from the `authority_level` and `source_class` it already reads for eligibility, so the hierarchy applies to the existing corpus with no schema change and no re-ingestion. `SourceVersion.effective_from` supplies the effective-date tie-break.

Entity type and reporting framework are not yet inputs to the ranking; they remain a judgement made in the answer, not in the sort.

## Recommended implementation order

1. OFAC, UN, UK, and EU sanctions data
2. EUR-Lex and Cellar
3. IMF and direct ECB data
4. Regulations.gov
5. FATF
6. IFRS and FASB licensing
7. IAASB, ICAI, and complete PCAOB coverage
8. India Code, CBDT, CBIC, MCA, SEBI, RBI, and FIU-IND
9. HMRC and legislation.gov.uk
10. TED, SAM.gov, Contracts Finder, CPPP, and other official procurement sources

## Phased API implementation register

Status is intentionally stricter than configuration: `QUERY_READY` means a normal Ask Kriton query can route to the provider, pass through retry/cache/governance, and produce a direct official citation.

| Phase | Source | Delivery status | Runtime requirement |
|---|---|---|---|
| 1 | ECB Data Portal | `QUERY_READY` | Keyless; `ENABLE_LIVE_SOURCES=true` and seeded provider |
| 1 | IMF DataMapper v2 | `QUERY_READY` | Keyless; upstream CDN availability; seeded provider |
| 1 | European Commission VIES | `QUERY_READY` | Keyless; current-date validation only; seeded provider |
| 1 | Regulations.gov v4 | `QUERY_READY_AFTER_KEY` | Free `REGULATIONS_GOV_API_KEY`; seeded provider |
| 2 | EUR-Lex / Cellar | `IMPLEMENTED_TIMEOUT_MITIGATED` | Query bounded to English expressions of works carrying a CELEX id, and given its own `CELLAR_SPARQL_TIMEOUT_SECONDS` budget rather than the shared 20s one; registered SOAP remains optional |
| 2 | legislation.gov.uk | `IMPLEMENTED_EDGE_BLOCKED` | The HTTP 202 is **not** an asynchronous feed build. Measured 1 August 2026: every endpoint — search feed, dated feed, and a direct document URI — returns 202 with `Content-Length: 0`, `Cache-Control: no-store` and `x-cache: Error from cloudfront`, and does not resolve after 26s of polling. That is a CDN edge rejection; the request is not reaching the origin from this network. The connector now fails fast on an empty 202 and only polls a 202 that carries a `Retry-After`, a `Location`, or a body |
| 2 | TED | `LIVE_VERIFIED` | Keyless TED v3 published-notice search; supported-field contract verified |
| 2 | SAM.gov | `QUERY_READY_AFTER_KEY` | Free `SAM_GOV_API_KEY`; public opportunities only |
| 3 | OFAC SLS | `IMPLEMENTED_UPSTREAM_403` | Parser/scheduler complete; official redirect returned 403 to this deployment's egress. Failover to `OFAC_SDN_XML_FALLBACK_URLS` is now attempted; a 403 caused by egress rather than by the address is a network fix, not a code fix |
| 3 | UN sanctions | `LIVE_VERIFIED_SYNC_REQUIRED` | 1,011 records observed 31 July 2026; pre-warmed hashed snapshot required |
| 3 | UK sanctions | `LIVE_VERIFIED_SYNC_REQUIRED` | Official ~49 MB CSV reachable; pre-warmed hashed snapshot required |
| 3 | EU sanctions | `IMPLEMENTED_UPSTREAM_403` | Parser/scheduler complete; official FSF distribution denied this deployment's egress. `EU_SANCTIONS_CSV_FALLBACK_URLS` accepts an alternate distribution once one is confirmed |
| 4 | HMRC | `PENDING_OAUTH_APPROVAL` | Developer account, sandbox, OAuth scopes, Fraud Prevention Headers, production approval |

### Running the scheduled sync

Sanctions feeds are never downloaded in an Ask Kriton request. Queries use only a fresh atomic snapshot under `SANCTIONS_SNAPSHOT_DIR` (default `backend/data/live_sources`); a missing or stale snapshot fails closed and falls back to other governed retrieval.

The schedule is defined in `app/jobs/live_sources_tasks.py` (`celery_app.conf.beat_schedule`) and needs both a worker and a beat process to exist — defining a Celery task schedules nothing on its own:

```
celery -A app.jobs.live_sources_tasks worker --loglevel=info --concurrency=2
celery -A app.jobs.live_sources_tasks beat   --loglevel=info
```

`docker compose up` runs both, against a `redis` broker, with the snapshot directory on a named volume shared with the API container. The first sync also runs during `seed`, so screening works from first boot rather than at the next tick. For a one-off refresh, run `python scripts/sync_sanctions_sources.py` from `backend`.

Two deployment requirements that are easy to miss:

- **The snapshot directory must be persistent and shared.** The worker writes it and the API reads it. On an ephemeral filesystem (Railway's default) snapshots vanish on every redeploy and screening silently returns to failing closed. Attach a volume, or accept a warm-up window.
- **Railway runs one process per service.** The worker and beat need their own services; `railway.json`'s start command covers the API only.

After each successful sync the provider's registry row records `last_successful_sync` and `last_content_hash`, so list freshness is answerable from the database rather than by inspecting a file on the worker's disk.

### Monitoring

`scripts/check_external_sources.py` is the upstream canary: it contacts every configured source for real, on a schedule, and is the only thing in the repository that does — the test suite mocks all of them, correctly, so a merge never fails because a government web server is slow.

Three rules it is built around, each learned from a real failure:

- **A response is only healthy if it carries content.** A 200 with zero records is the signature of contract drift, and the previous check reported it as `live`.
- **Probes target the current period.** A probe pinned to a past year answers forever out of an archive while current data quietly stops flowing.
- **Nothing here downloads a bulk feed.** Sanctions lists are checked with a ranged request; the previous check read the local snapshot file and so reported `live` for lists nobody had been able to download in weeks.

Reports are printed with credentials redacted — several of these APIs take their key as a query parameter, and `httpx` puts the full URL into its exceptions, so an upstream 4xx would otherwise reproduce the key in a retained CI artifact.

`scripts/diff_provider_health.py` compares two reports and alerts on a **transition**, not a state. Two sources fail persistently for reasons no code change fixes; a job that goes red for those every day is a job everyone learns to ignore. `GET /api/v1/live-sources/health` exposes the same freshness data from the registry, and the Status & Health page renders it.

Phase 1 code lives under `backend/app/domains/live_sources/`. Metric providers use `LiveSourceConnector`; record providers use `EvidenceSearchConnector`. Later phases must extend these contracts rather than bypassing the governed retrieval and citation path.

### Two ways to reach a record provider

An Ask Kriton query answers a question and cites the single best record: `EvidenceLiveConnector` adapts an `EvidenceSearchConnector` down to one `NormalizedResponse`.

`POST /api/v1/live-sources/evidence/search` returns the full result set instead, for the reviewer question an answer cannot express — "every current official record matching this". It is authenticated, rate limited, and gated on the same `LiveSourceProvider` row the licence gate applies to a live source used in an answer: unknown or tenant-private providers return 404, disabled 409, licence-restricted 403. `GET /api/v1/live-sources/evidence/providers` lists the searchable keys.

Both paths share one retry policy (`app/domains/live_sources/retry.py`): transport failures, 429 and 5xx are retried; 403 and 404 are stable answers and are not.

## Governing rule

> Kriton may use broad discovery to locate information, but every professional claim must be supported by the correct jurisdiction's controlling or explicitly authoritative source. Free access does not remove copyright, attribution, licensing, privacy, or redistribution obligations.
