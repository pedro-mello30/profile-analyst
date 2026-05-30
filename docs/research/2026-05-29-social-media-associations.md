# Research Dossier — Social-Media Associations Profile System

**Date:** 2026-05-29  
**Scope:** Instagram-seeded unified dossier for influencer-marketing analytics.  
**Purpose:** Ground-truth citations and findings for `specs/0001-social-media-associations-profile/spec.md`.

---

## 1. User Identity Linkage (UIL) / Cross-Platform Identification

### 1.1 Surveys & Foundations

**Shu et al. (2017)** — the ACM SIGKDD survey — frames UIL as two-phase: (1) feature extraction
and (2) predictive modeling, surveying rule-based, supervised, and network-embedding families.

> Shu, K., Wang, S., Tang, J., Zafarani, R., & Liu, H. (2017). "User Identity Linkage across Online
> Social Networks: A Review." *ACM SIGKDD Explorations Newsletter*, 18(2), 5–17.
> DOI: 10.1145/3068777.3068781 | https://dl.acm.org/doi/10.1145/3068777.3068781

**Senette, Siino & Tesconi (2024)** — IEEE Access survey (25 pp, 2016–present) — catalogues
11 feature categories, 16 reusable datasets, two problem formulations (network alignment vs.
classification), and five open problems: dynamic networks, unsupervised models, LLM integration,
evaluation standardization, privacy-preservation.

> Senette, C., Siino, M., & Tesconi, M. (2024). "User Identity Linkage on Social Networks: A Review
> of Modern Techniques and Applications." *IEEE Access*, 12, 171241–171268.
> arXiv: 2409.08966 | https://arxiv.org/abs/2409.08966

**Narayanan & Shmatikov (2009)** — established the security foundation: structural-only graph
attack re-identified ~33% of Twitter/Flickr overlap users. No profile text required.

> Narayanan, A., & Shmatikov, V. (2009). "De-anonymizing Social Networks." *IEEE S&P 2009*, 173–187.
> DOI: 10.1109/SP.2009.22 | arXiv: 0903.3276 | https://arxiv.org/abs/0903.3276

### 1.2 Feature Taxonomy

Five categories appear consistently across the literature:

**A. Username / Handle Patterns**  
~45% of Google and Twitter users share identical usernames. Jaro-Winkler/Levenshtein matching
achieves ~70–73% accuracy; exact match ~92% when reused.

> Zafarani, R., & Liu, H. (2013). "Connecting Users across Social Media Sites: A Behavioral-Modeling
> Approach." *KDD 2013*, 41–49. DOI: 10.1145/2487575.2487648
> https://dl.acm.org/doi/pdf/10.1145/2487575.2487648

**B. Profile Attributes**  
Name similarity, profile photo (perceptual hashing / CNN embeddings), bio text, URL links,
join date, follower/following counts. Multi-attribute fusion (LINKSOCIAL) achieved 92%.

**C. Writing Style / Stylometry**  
Temporal-linguistic models (n-grams, function words, punctuation, posting rhythm). Correctly
matched 31% of 5,612 users across Twitter and Facebook.

> Vosoughi, S., Zhou, H., & Roy, D. (2015). "Digital Stylometry: Linking Profiles Across Social
> Networks." *SocInfo 2015* (LNCS). arXiv: 1605.05166 | https://arxiv.org/abs/1605.05166

**D. Network / Graph Structure**  
IONE preserves follower/followee proximity via intra/inter-network embedding (unsupervised).
PALE uses supervised embedding with known anchor pairs. DeepLink adds deep autoencoder.

> Liu, L., Cheung, W. K., Li, X., & Liao, L. (2016). "Aligning Users across Social Networks Using
> Network Embedding (IONE)." *IJCAI 2016*, 1774–1780.
> https://github.com/ColaLL/IONE

> Man, T., Shen, H., Liu, S., Jin, X., & Cheng, X. (2016). "Predict Anchor Links across Social
> Networks via an Embedding Approach (PALE)." *IJCAI 2016*, 1823–1829.
> https://dblp.org/rec/conf/ijcai/ManSLJC16.html

> Zhou, F., Liu, L., Zhang, K., Trajcevski, G., Wu, J., & Zhong, T. (2018). "DeepLink: A Deep
> Learning Approach for User Identity Linkage." *IEEE INFOCOM 2018*, 1313–1321.
> https://kpzhang.github.io/paper/INFOCOMM2018.pdf

> Zhang, K., & Shu, K. (2019). "Graph Neural Networks for User Identity Linkage." arXiv: 1903.02174.
> https://arxiv.org/abs/1903.02174

**E. Spatio-Temporal / Behavioral**  
Timestamped location data from just two apps sufficient to link users via max-weight matching.

> Goga, O., Lei, H., Parthasarathi, S. H. K., Friedland, G., Sommer, R., & Teixeira, R. (2013).
> "Exploiting Innocuous Activity for Correlating Users Across Sites." *WWW 2013*, 447–458.
> DOI: 10.1145/2488388.2488428

> Riederer, C. J., Kim, Y., Chaintreau, A., Korula, N., & Lattanzi, S. (2016). "Linking Users Across
> Domains with Location Data: Theory and Validation." *WWW 2016*, 707–719.
> DOI: 10.1145/2872427.2883002

### 1.3 Method Families & Accuracy

| Family | Methods | Notes |
|---|---|---|
| Rule / heuristic | Exact username match, Jaro-Winkler | Precision 90%+ when handles reused; recall low |
| Supervised matching | MOBIUS (Zafarani & Liu 2013), SVM | Pairwise ~80–92% |
| Unsupervised embedding | IONE (IJCAI 2016) | Competitive without anchor pairs |
| Supervised embedding | PALE (IJCAI 2016), DeepLink (INFOCOM 2018) | State-of-art on Twitter-Foursquare |
| GNN-based | GraphUIL (2019), UIL-HGAN (2020) | Higher-order neighborhood; outperform shallow |
| Stylometric | Vosoughi et al. 2015 | 31% top-1; improves with more text |

**Benchmark datasets:** Twitter–Foursquare dominant; Senette et al. (2024) catalogs 16 public
datasets. Dataset scarcity is a persistent reproducibility problem.

---

## 2. Entity Resolution / Record Linkage

### 2.1 Foundations

**Fellegi-Sunter (1969)** — Bayesian framework: pair classified as Link / Non-link / Possible-link
based on m- and u-probability likelihood ratio. Foundational for any profile-matching pipeline.

> Fellegi, I. P., & Sunter, A. B. (1969). "A Theory for Record Linkage." *JASA*, 64(328), 1183–1210.
> DOI: 10.1080/01621459.1969.10501049

**Blocking / Candidate generation** — avoids O(n²) comparisons. LSH generalizes to high-dimensional
embeddings; semantically similar records land in the same bucket with high probability.

> Papadakis, G., Skoutas, D., Thanos, E., & Palpanas, T. (2020). "Blocking and Filtering Techniques
> for Entity Resolution: A Survey." *ACM Computing Surveys*, 53(2). DOI: 10.1145/3377455

> Christen, P. (2012). *Data Matching: Concepts and Techniques for Record Linkage, Entity Resolution,
> and Duplicate Detection*. Springer. ISBN: 978-3-642-31164-2.
> https://link.springer.com/book/10.1007/978-3-642-31164-2

---

## 3. Attribute & Demographic Inference

### 3.1 Key findings

Facebook Likes alone (SVD + logistic regression) predicted sexual orientation (88%), political
affiliation, ethnicity, religion, intelligence, age, gender — establishing the upper bound on
what engagement signals can reveal. **Critical privacy implication for this system.**

> Kosinski, M., Stillwell, D., & Graepel, T. (2013). "Private traits and attributes are predictable
> from digital records of human behavior." *PNAS*, 110(15), 5802–5805. DOI: 10.1073/pnas.1218772110

Twitter n-gram + sociolinguistic features predicted gender (72.3%), age group, regional origin,
political orientation from tweet text.

> Rao, D., Yarowsky, D., Shreevats, A., & Gupta, M. (2010). "Classifying Latent User Attributes
> in Twitter." *SMUC 2010*, 37–44. DOI: 10.1145/1871985.1871993

### 3.2 Fairness / Bias

**Commercial gender classifiers show intersectional bias:** 0.8% error for light-skinned males
vs 34.7% for dark-skinned females. Directly transferable to social-media demographic inference.

> Buolamwini, J., & Gebru, T. (2018). "Gender Shades: Intersectional Accuracy Disparities in
> Commercial Gender Classification." *FAT* 2018*, PMLR 81.
> https://proceedings.mlr.press/v81/buolamwini18a.html

**Implication for this system:** Never emit binary-gender or ethnicity scores by default. Mark
any demographic inference with `art9_risk: true` and require explicit consent for downstream use.

---

## 4. Social Network Analysis for "Associations"

### 4.1 Community Detection

> Blondel, V. D., Guillaume, J.-L., Lambiotte, R., & Lefebvre, E. (2008). "Fast unfolding of
> communities in large networks (Louvain)." *Journal of Statistical Mechanics*, P10008.
> DOI: 10.1088/1742-5468/2008/10/P10008

> Traag, V. A., Waltman, L., & van Eck, N. J. (2019). "From Louvain to Leiden: guaranteeing
> well-connected communities." *Scientific Reports*, 9, 5233. DOI: 10.1038/s41598-019-41695-z

**Preference: Leiden** — guarantees connected communities and local optimality; preferred for
production influencer graphs.

### 4.2 Tie Strength & Homophily

> Granovetter, M. S. (1973). "The Strength of Weak Ties." *American Journal of Sociology*, 78(6),
> 1360–1380. DOI: 10.1086/225469

Weak ties bridge communities and carry novel information; strong ties reinforce clusters.
**For influencer marketing:** strong ties = collaboration candidates; weak ties = cross-niche bridges.

> McPherson, M., Smith-Lovin, L., & Cook, J. M. (2001). "Birds of a Feather: Homophily in Social
> Networks." *Annual Review of Sociology*, 27, 415–444. DOI: 10.1146/annurev.soc.27.1.415

Demographic homophily produces coherent audience niches — explains audience segmentation.

### 4.3 Link Prediction

> Liben-Nowell, D., & Kleinberg, J. (2007). "The link-prediction problem for social networks."
> *JASIST*, 58(7), 1019–1031. DOI: 10.1002/asi.20591

Common neighbors, Jaccard, Adamic-Adar, preferential attachment — applicable to predicting
influencer collaboration or audience overlap growth.

---

## 5. Influencer Analytics — Feature Catalog (61 items)

Basis for `specs/0001-…/spec.md §5`. Items marked [★v1] are computable from a single public
profile without creator consent. Others require creator OAuth or multi-profile data.

### 5.1 Engagement

| # | Feature | Formula | v1? |
|---|---|---|---|
| 1 | ER by Followers | `(Likes+Comments+Saves+Shares) / Followers × 100` | ★v1 |
| 2 | ER by Reach | `Engagements / Reach × 100` | needs reach |
| 3 | ER by Impressions | `Engagements / Impressions × 100` | needs impressions |
| 4 | ER by Views | `Engagements / Views × 100` | video only |
| 5 | Save Rate | `Saves / Reach × 100` | needs reach |
| 6 | Share Rate | `Shares / Reach × 100` | needs reach |
| 7 | Comments per Post | avg over 30-day window | ★v1 |

**Benchmarks (December 2025, ClickAnalytic):** Nano 8–15%, Micro median ~0.80%, Macro ~1.02%,
Mega ~1.10%, Celebrity ~1.20%. Cross-platform: Instagram 1.4–3.2%, TikTok 3–7%, YouTube 0.5–2%.
(Note: nano-beats-macro rule doesn't hold here — use reach-based ER for fair comparison.)

**Saves** carry the highest conversion-predictive weight (3.5x over likes-only, Later 2025).

### 5.2 Reach & Visibility

| # | Feature | Notes | v1? |
|---|---|---|---|
| 8 | Follower Count | raw | ★v1 |
| 9 | Follower Tier | Nano 1K–10K, Micro 10K–100K, Macro 100K–1M, Mega 1M+ | ★v1 |
| 10 | Estimated Reach per Post | inferred from ER + followers | ★v1 [inferred] |
| 11 | Organic Reach Rate | `Reach / Followers × 100` | needs reach |
| 12 | Audience Reachability | % followers following <500 accounts | multi-profile |
| 13 | Story Reach | Stories-specific analytics | creator auth |

### 5.3 Growth

| # | Feature | Formula | v1? |
|---|---|---|---|
| 14 | Follower Growth Rate | `(New-Lost) / Start × 100` | needs history |
| 15 | Growth Velocity | rate-of-change of growth rate | needs history |
| 16 | Follower Spike Detection | sudden abnormal growth event | needs history |
| 17 | Following Growth Rate | rate of change of following count | needs history |

### 5.4 Posting Behavior

| # | Feature | Notes | v1? |
|---|---|---|---|
| 18 | Posting Frequency | posts/week by format | ★v1 |
| 19 | Posting Consistency Score | variance in inter-post intervals | ★v1 |
| 20 | Content Cadence Trend | rolling window comparison | needs history |

### 5.5 Content Classification

| # | Feature | Signals | v1? |
|---|---|---|---|
| 21 | Primary Content Niche | NLP captions/hashtags + CV images | ★v1 (NLP; CV optional) |
| 22 | Secondary Niches | top-N categories | ★v1 |
| 23 | Hashtag Fingerprint | characteristic hashtag clusters | ★v1 |
| 24 | Content Language | primary caption language | ★v1 |

**Image features dominate on Instagram** (90.75% accuracy vs 60.9% text-only for niche classification).

> "Multimodal Post Attentive Profiling for Influencer Marketing" (WWW 2020, ACM).
> https://dl.acm.org/doi/fullHtml/10.1145/3366423.3380052

### 5.6 Audience Quality & Authenticity

| # | Feature | Notes | v1? |
|---|---|---|---|
| 25 | Real Follower % | ML classifier on follower profiles | multi-profile |
| 26 | Influencer Follower % | % followers themselves influencers | multi-profile |
| 27 | Mass Follower % | % following >1,500 accounts | multi-profile |
| 28 | Suspicious Account % | bot/inactive classifier | multi-profile |
| 29 | Audience Quality Score | composite 1–100 | multi-profile |
| 30 | Comment Authenticity Rate | % not in pods/tag schemes | ★v1 [heuristic] |
| 31 | Engagement Pod Detection | timing clustering + text similarity | ★v1 [heuristic] |

### 5.7 Fake Follower / Fraud Detection

**Botometer (Varol et al. 2017):** 1,150 features, 6 classes, Random Forest. 9–15% of Twitter
accounts are bots. Metadata features most informative. Note: Twitter-trained; Instagram requires
feature re-engineering.

> Varol, O., Ferrara, E., Davis, C.A., Menczer, F., Flammini, A. (2017). "Online Human-Bot
> Interactions: Detection, Estimation, and Characterization." *ICWSM 2017*. arXiv: 1703.03107

**Cresci et al. (2017) — Social Fingerprinting (digital DNA):** Encodes account lifetime as
character string of action types; edit-distance similarity detects coordinated groups even when
individual accounts appear human. Paradigm shift paper on next-gen spambots.

> Cresci, S., Di Pietro, R., Petrocchi, M., Spognardi, A., Tesconi, M. (2017). "The Paradigm-Shift
> of Social Spambots." *WWW Companion 2017*. arXiv: 1701.03017

> Cresci, S., Di Pietro, R., Petrocchi, M., Spognardi, A., Tesconi, M. (2017). "Social
> Fingerprinting: Detection of Spambot Groups through DNA-Inspired Behavioral Modeling."
> *IEEE TDSC*. arXiv: 1703.04482

**Instagram-specific ML (ResearchGate 2022):** 65,326 accounts; Neural Network F1 = 0.89.
Features: bio completeness, profile photo, follower/following ratio, account age, username
randomness.

| # | Feature | Notes | v1? |
|---|---|---|---|
| 32 | Fake Follower % | growth spike + follower profile ML | multi-profile |
| 33 | Fraud Risk Score | composite | multi-profile |
| 34 | Bot Score per Follower | Botometer-style on follower sample | multi-profile |
| 35 | Coordination Signal | Cresci social fingerprinting | multi-profile |

**v1 heuristics (single profile, no follower-list access):**
- Follower/following ratio anomaly
- Rapid growth spike in available history
- Generic comment patterns (pod detection via text similarity)
- Account metadata completeness

### 5.8 Audience Demographics

| # | Feature | Source | v1? |
|---|---|---|---|
| 36 | Age Distribution | Instagram API (creator-consented) | deferred |
| 37 | Gender Split | Instagram API | deferred |
| 38 | Top Countries (up to 45) | Instagram API | deferred |
| 39 | Top Cities (up to 45) | Instagram API | deferred |
| 40 | Audience Language | Instagram API + NLP | deferred |
| 41 | Audience Active Hours | Instagram API | deferred |

**API reality:** Demographics endpoint only accessible to the authenticated account owner.
Third-party platforms either use creator-consent flows (Phyllo) or infer from public signals
(accuracy ~70–85%). Always mark inferred demographics as `confidence: <0.85, method: inferred`.

### 5.9 Brand & Affinity

| # | Feature | Signals | v1? |
|---|---|---|---|
| 42 | Influencer Brand Affinity | NLP (mentions/hashtags) + CV logo + location tags | ★v1 (NLP; CV optional) |
| 43 | Audience Brand Affinity | follower activity signals aggregated | multi-profile |
| 44 | Sponsorship History | sponsored post detection timeline | ★v1 |
| 45 | Exclusivity Risk | competing brand active partnership | ★v1 [inferred] |
| 46 | Brand Safety Signal | NLP classifier on unsafe topics | ★v1 |

### 5.10 Sponsored Content Detection

| # | Feature | Method | v1? |
|---|---|---|---|
| 47 | Disclosed Sponsored Post Flag | #ad / Paid Partnership tag parsing | ★v1 (rule-based) |
| 48 | Undisclosed Sponsored Post Flag | multimodal classifier F1 ≈ 0.93 | ★v1 (LLM) |
| 49 | FTC Compliance Score | disclosure language consistency | ★v1 [inferred] |

**LLM-based sponsored detection achieves F1 up to 0.93.**

> "InstaSynth: Opportunities and Challenges in Generating Synthetic Instagram Data with ChatGPT
> for Sponsored Content Detection." *ICWSM 2024*. https://arxiv.org/html/2403.15214v1

### 5.11 Associations / Network

| # | Feature | Method | v1? |
|---|---|---|---|
| 50 | Pairwise Audience Overlap | Jaccard (usually inferred) | multi-profile |
| 51 | Audience Overlap Matrix | N×N for creator set | multi-profile |
| 52 | De-duplicated Campaign Reach | overlap matrix + individual reaches | multi-profile |
| 53 | Creator Similarity Score | multimodal embedding cosine similarity | multi-profile |
| 54 | Content Niche Overlap | topic vector similarity | multi-profile |
| 55 | Influential Fan Discovery | creator universe ∩ brand's followers | multi-profile |

### 5.12 Centrality / Network Influence

| # | Feature | Definition | v1? |
|---|---|---|---|
| 56 | Follower/Following Ratio | `Followers / Following` | ★v1 |
| 57 | PageRank Score | importance weighted by follower importance | graph-stage |
| 58 | Betweenness Centrality | information broker position | graph-stage |

### 5.13 ROI & Value

| # | Feature | Notes | v1? |
|---|---|---|---|
| 59 | Earned Media Value (EMV) | `Impressions × CPM` — no universal standard | ★v1 [inferred, no std] |
| 60 | Cost Per Engagement (CPE) | `Spend / Engagements` | campaign integration |
| 61 | Conversion Rate | UTM-tracked clicks + conversions | campaign integration |

---

## 6. Data Access & Legal Landscape (2025–26)

### 6.1 Official Instagram APIs

**Basic Display API:** shut down **2024-12-04**. Personal accounts have no supported API path.

> Meta Developer Blog — Update on Instagram Basic Display API (Sept 4, 2024):
> https://developers.facebook.com/blog/post/2024/09/04/update-on-instagram-basic-display-api/

**Instagram Graph API (active, 2 configurations):**

| Config | Auth | Base URL |
|---|---|---|
| Facebook Login | Facebook OAuth | graph.facebook.com |
| Instagram Login (new 2024) | Instagram OAuth | graph.instagram.com |

Eligibility: account holder must have a Business or Creator (Professional) Instagram account.

**Key endpoints:**
- `/me`, `/{id}/media`, `/{id}/insights` — authenticated account owner only
- `business_discovery` — public profile fields of OTHER Business/Creator accounts (no follower
  lists, no third-party audience demographics, no personal accounts)

**Rate limits:** 200 calls/hour per Instagram Business account.

**What is NOT available officially:** follower/following lists, audience demographics of
non-owned accounts, personal account data, arbitrary public post discovery.

> Meta Platform Overview: https://developers.facebook.com/docs/instagram-platform/overview/

### 6.2 Third-Party Providers

| Provider | Type | Key Data | Notes |
|---|---|---|---|
| Apify | Scraper-as-a-Service | profiles, posts, comments, reels | ~$1.50/1k posts; outside Meta ToS |
| Bright Data | Dataset broker + scraper | followers, verified status, posts, engagement | ~$600/100K profiles; won Meta lawsuit |
| Phyllo | Consent-based | first-party analytics, private metrics, demographics | $199+/mo; legally cleanest |
| InsightIQ | Hybrid | 250M+ influencers, audience demographics | enterprise pricing |
| HypeAuditor | Analytics platform | AQS, audience quality, demographics, API | $10k+/year |

### 6.3 Case Law (2021–2024)

**Van Buren v. United States, 593 U.S. 374 (2021):** CFAA "exceeds authorized access" means
genuinely off-limits areas, not ToS violations. Scraping publicly accessible websites does NOT
constitute a CFAA violation.

**hiQ Labs, Inc. v. LinkedIn Corp. (9th Cir. 2022 + settlement 2022):** 9th Circuit: automated
capture of publicly accessible data does not violate CFAA. Settlement: hiQ agreed to injunction
(contract + unfair competition theory, not CFAA). CFAA precedent intact.

**Meta Platforms, Inc. v. Bright Data Ltd. (N.D. Cal., ruling 2024-01-23):** Meta's Facebook and
Instagram Terms of Service **do not prohibit logged-off scraping of publicly available data**.
Summary judgment for Bright Data. Meta dropped remaining claims 2024-02-23 without settlement.

> https://techcrunch.com/2024/01/24/court-rules-in-favor-of-a-web-scraper-bright-data-which-meta-had-used-and-then-sued/
> https://www.quinnemanuel.com/the-firm/news-events/client-alert-meta-v-bright-data-significant-decision-for-web-scraping-industry/

**Key nuance:** The Bright Data ruling is limited to *logged-off* scraping. Authenticated scraping
almost certainly violates ToS. Technical enforcement (bot detection, IP banning) continues
regardless of legal posture.

### 6.4 GDPR

**Art. 6 — Lawful basis:** Legitimate Interests (Art. 6(1)(f)) for B2B influencer analytics of
public data; requires Legitimate Interests Assessment (LIA). Consent required for private
analytics or EU-resident profiles with sensitivity concerns.

**Art. 9 — Special category data:** Public posts may inadvertently reveal health, sexual
orientation, religion, political views — even via inference. Processing these requires **explicit
consent** or an Art. 9(2) exception. This system must flag all inferences that touch Art. 9 data.

**Art. 22 — Automated decision-making & profiling:** Applies when processing "significantly
affects" a data subject (e.g., influencer selection for campaigns). Requires: valid lawful basis,
human review right, right to contest, meaningful explanation of logic.

> GDPR Art. 22: https://gdpr-info.eu/art-22-gdpr/
> ICO guidance: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/rights-related-to-automated-decision-making-including-profiling/

**Data minimization (Art. 5(1)(c)):** Collect only what is demonstrably necessary. Short
retention for scraped data (recommendation: 90 days max for raw scrape; consent-based longer
with deletion-on-request support).

### 6.5 CCPA/CPRA

- "Publicly available information" exemption narrows under CPRA.
- CPRA ADMT Regulations (adopted 2025, eff. **2026-01-01**): automated decision-making that
  substantially replaces human decisions for "significant decisions" (influencer selection could
  qualify) requires pre-use risk assessments and opt-out rights.

> https://cppa.ca.gov/faq.html

### 6.6 FTC Endorsement Guides

**Effective October 2023 (enforced through 2024–2025).** Core: any "material connection"
(cash, gift, employment, family) must be **clearly and conspicuously disclosed** — not buried in
hashtag clouds. "#ad" remains widely used but placement must be unavoidable.

Platform-native tags (Instagram "Paid Partnership", YouTube "Paid Promotion") are **insufficient
alone** — FTC requires manual disclosure within content.

AI-generated content: double disclosure (sponsorship + AI-generated nature).

**Penalties:** up to ~$53,088 per violation (inflation-adjusted annually).

> FTC Endorsement Guides: https://www.ftc.gov/business-guidance/advertising-marketing/endorsements-influencers-reviews
> Disclosures 101: https://www.ftc.gov/system/files/documents/plain-language/1001a-influencer-guide-508_1.pdf

---

## 7. Existing Tools — Feature Benchmarks

| Platform | DB Size | Key Differentiators |
|---|---|---|
| HypeAuditor | 226.9M+ | AQS (15 sub-metrics), 50+ fraud patterns, 95.5% fraud detection (self-reported) |
| Modash | 350M+ | City-level location filters, influential fans/customers, API available |
| Klear (Meltwater) | 1M+ topics | Influence Score (0–100), True Reach proprietary |
| CreatorIQ | Enterprise | AI audience overlap matrix, brand affinity filtering |
| Influencity | Mid-market | Brand affinity NLP+CV, pod detection, follower quality |
| IQFluence | Audience overlap | Jaccard overlap with demographic breakdown |

**HypeAuditor AQS components:** (1) Engagement Rate, (2) Quality Audience %, (3) Follower Growth
Patterns, (4) Comments Authenticity. 15 sub-metrics total.

---

## 8. Limitations & Threats to Validity

1. **Data sparsity** — most users populate only a subset of profile fields; cold-start conditions
   produce no features. (Senette et al. 2024)
2. **Profile evolution & temporal drift** — usernames change, accounts deleted, behavior shifts.
   Existing methods treat networks as static snapshots. (Open problem: Senette et al. 2024)
3. **Adversarial evasion** — deliberate handle variation, VPN, persona partitioning significantly
   harder to link. Poisoning strategies degrade UIL model performance.
   arXiv: 2209.00269 | https://arxiv.org/abs/2209.00269
4. **Label scarcity** — supervised UIL requires labeled anchor pairs (expensive); selection bias
   toward users who voluntarily cross-link accounts.
5. **Fairness & representational bias** — models trained on English/US data perform poorly on
   other languages and cultures. Binary gender enforces heteronormative assumptions.
   (Buolamwini & Gebru 2018)
6. **Privacy & legal constraints** — re-identification across platforms may require processing
   personal data without consent; inferred special-category data (GDPR Art. 9) even from public
   posts; one-to-one constraint breaks in practice (brand vs personal accounts, sock puppets).
7. **Audience overlap accuracy** — Jaccard on exact follower lists is theoretically ideal but
   blocked by API restrictions. Commercial implementations report ~70–85% accuracy via inference.
8. **EMV lacks a universal formula** — vendor-chosen CPM multipliers vary significantly; mark as
   indicative only.

---

## 9. Consolidated Bibliography

1. Blondel, V. D., Guillaume, J.-L., Lambiotte, R., & Lefebvre, E. (2008). Louvain algorithm.
   *Journal of Statistical Mechanics*, P10008. DOI: 10.1088/1742-5468/2008/10/P10008

2. Buolamwini, J., & Gebru, T. (2018). Gender Shades. *FAT* 2018*, PMLR 81.
   https://proceedings.mlr.press/v81/buolamwini18a.html

3. Christen, P. (2012). *Data Matching*. Springer. ISBN: 978-3-642-31164-2.

4. Cresci, S., et al. (2015). "Fame for Sale." *Decision Support Systems 80*.

5. Cresci, S., et al. (2017). "The Paradigm-Shift of Social Spambots." *WWW Companion*.
   arXiv: 1701.03017

6. Cresci, S., et al. (2017). "Social Fingerprinting." *IEEE TDSC*. arXiv: 1703.04482

7. Fellegi, I. P., & Sunter, A. B. (1969). Record Linkage theory. *JASA*, 64(328).
   DOI: 10.1080/01621459.1969.10501049

8. Getoor, L., & Machanavajjhala, A. (2012). Entity Resolution. *PVLDB*, 5(12).

9. Goga, O., et al. (2013). Correlating users across sites. *WWW 2013*.
   DOI: 10.1145/2488388.2488428

10. Granovetter, M. S. (1973). Strength of Weak Ties. *AJS*, 78(6). DOI: 10.1086/225469

11. Kosinski, M., Stillwell, D., & Graepel, T. (2013). Private traits. *PNAS* 110(15).
    DOI: 10.1073/pnas.1218772110

12. Liben-Nowell, D., & Kleinberg, J. (2007). Link prediction. *JASIST* 58(7).
    DOI: 10.1002/asi.20591

13. Liu, L., et al. (2016). IONE. *IJCAI 2016*.

14. Man, T., et al. (2016). PALE. *IJCAI 2016*.

15. McPherson, M., Smith-Lovin, L., & Cook, J. M. (2001). Homophily. *Annual Review Sociology* 27.
    DOI: 10.1146/annurev.soc.27.1.415

16. Narayanan, A., & Shmatikov, V. (2009). De-anonymizing Social Networks. *IEEE S&P 2009*.
    arXiv: 0903.3276

17. Papadakis, G., et al. (2020). Blocking and Filtering for ER. *ACM CSUR* 53(2).
    DOI: 10.1145/3377455

18. Rao, D., et al. (2010). Latent User Attributes in Twitter. *SMUC 2010*.
    DOI: 10.1145/1871985.1871993

19. Riederer, C. J., et al. (2016). Linking Users via Location Data. *WWW 2016*.
    DOI: 10.1145/2872427.2883002

20. Senette, C., Siino, M., & Tesconi, M. (2024). UIL Review. *IEEE Access* 12. arXiv: 2409.08966

21. Shu, K., et al. (2017). UIL Review. *ACM SIGKDD Explorations* 18(2).
    DOI: 10.1145/3068777.3068781

22. Traag, V. A., Waltman, L., & van Eck, N. J. (2019). Leiden algorithm. *Scientific Reports* 9.
    DOI: 10.1038/s41598-019-41695-z

23. Varol, O., et al. (2017). Botometer. *ICWSM 2017*. arXiv: 1703.03107

24. Vosoughi, S., Zhou, H., & Roy, D. (2015). Digital Stylometry. *SocInfo 2015*.
    arXiv: 1605.05166

25. Zafarani, R., & Liu, H. (2013). MOBIUS. *KDD 2013*. DOI: 10.1145/2487575.2487648

26. Zhang, K., & Shu, K. (2019). GNN for UIL. arXiv: 1903.02174

27. Zhou, F., et al. (2018). DeepLink. *IEEE INFOCOM 2018*.
    https://kpzhang.github.io/paper/INFOCOMM2018.pdf

28. "Multimodal Post Attentive Profiling for Influencer Marketing." *WWW 2020, ACM*.
    https://dl.acm.org/doi/fullHtml/10.1145/3366423.3380052

29. "InstaSynth." *ICWSM 2024*. https://arxiv.org/html/2403.15214v1

30. Meta v. Bright Data ruling summary:
    https://www.quinnemanuel.com/the-firm/news-events/client-alert-meta-v-bright-data-significant-decision-for-web-scraping-industry/
