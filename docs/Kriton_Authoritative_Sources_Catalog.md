# Kriton Authoritative Sources Catalog

**Status:** Working source-integration register  
**Last reviewed:** 31 July 2026  
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

Implemented integrations include World Bank, ONS, Bank of England, Frankfurter FX, FRED, SEC EDGAR, Companies House, OECD, GLEIF, US Treasury Fiscal Data, Census, BLS, BEA, GovInfo, eCFR, Federal Register, and Congress.gov. IRS, FASB, PCAOB, SEC filing retrieval, Companies House documents, and US tax-regulation coverage are partial.

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
| Regulations.gov | US | `LIVE_API` | Free API key | Configured, adapter missing | [Regulations.gov API](https://open.gsa.gov/api/regulationsgov/) |

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

```text
source_id
authority_name
authority_rank
jurisdiction
domain
integration_type
official_url
api_base_url
authentication_type
pricing_model
licence_terms_url
publication_date
effective_date
superseded_date
last_successful_sync
freshness_sla
content_hash
display_permission
export_permission
tenant_entitlement
```

## Default authority hierarchy

1. Enacted legislation, official regulations, and binding court decisions
2. Applicable regulator, tax authority, or accounting/auditing standard setter
3. Official company registry or government filing system
4. Official international organization
5. Recognized professional-body guidance
6. Commercial or secondary discovery source

The hierarchy must also account for jurisdiction, effective date, entity type, reporting framework, and the exact query. International models and professional guidance must not override binding domestic implementation.

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
| 2 | EUR-Lex / Cellar | `IMPLEMENTED_UPSTREAM_TIMEOUT` | Public SPARQL connector complete; live probe exceeded 30 seconds; registered SOAP remains optional |
| 2 | legislation.gov.uk | `IMPLEMENTED_UPSTREAM_202` | Atom connector complete; current host repeatedly returned asynchronous HTTP 202 |
| 2 | TED | `LIVE_VERIFIED` | Keyless TED v3 published-notice search; supported-field contract verified |
| 2 | SAM.gov | `QUERY_READY_AFTER_KEY` | Free `SAM_GOV_API_KEY`; public opportunities only |
| 3 | OFAC SLS | `IMPLEMENTED_UPSTREAM_403` | Parser/scheduler complete; official redirect blocked this deployment network |
| 3 | UN sanctions | `LIVE_VERIFIED_SYNC_REQUIRED` | 1,011 records observed 31 July 2026; pre-warmed hashed snapshot required |
| 3 | UK sanctions | `LIVE_VERIFIED_SYNC_REQUIRED` | Official ~49 MB CSV reachable; pre-warmed hashed snapshot required |
| 3 | EU sanctions | `IMPLEMENTED_UPSTREAM_403` | Parser/scheduler complete; official FSF distribution denied this deployment network |

Sanctions feeds are never downloaded in an Ask Kriton request. Run `python scripts/sync_sanctions_sources.py` from `backend`, or schedule the `sync_sanctions_snapshots` Celery task. Queries use only a fresh atomic snapshot under `backend/data/live_sources`. Missing/stale snapshots fail closed and fall back to other governed retrieval.
| 4 | HMRC | `PENDING_OAUTH_APPROVAL` | Developer account, sandbox, OAuth scopes, Fraud Prevention Headers, production approval |

Phase 1 code lives under `backend/app/domains/live_sources/`. Metric providers use `LiveSourceConnector`; record providers use `EvidenceSearchConnector`. Later phases must extend these contracts rather than bypassing the governed retrieval and citation path.

## Governing rule

> Kriton may use broad discovery to locate information, but every professional claim must be supported by the correct jurisdiction's controlling or explicitly authoritative source. Free access does not remove copyright, attribution, licensing, privacy, or redistribution obligations.
