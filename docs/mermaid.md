flowchart TD
    CLI["tools/discover.py\n--handle"]
    subgraph DISCOVERY["Account Discovery Engine (spec-0018)"]
        RES["Username Resolver\ngenerate candidate usernames"]
        LINK["Link Expander\nbio links → Linktree / Beacons"]
        ENUM["Platform Enumerator\nMaigret username-check × N platforms"]
        OSINT["OSINT Cross-Reference\nHolehe / GHunt (email → services)"]
        RANK["Confidence Ranker\ndedup + score per account"]
        MW["Manifest Writer\n00-discovery.json"]
    end

    subgraph DOWNSTREAM["Existing pipeline (unchanged)"]
        S1["Stage 1 INGEST\n01-raw.json\n(picks up 00-discovery if present)"]
        S1B["Stage 1B ENRICHMENT\n(spec 0014)"]
        S6["Stage 6 DOSSIER"]
    end

    CLI --> RES
    RES --> LINK
    RES --> ENUM
    LINK -->|discovered email| OSINT
    ENUM -->|discovered email| OSINT
    LINK --> RANK
    ENUM --> RANK
    OSINT --> RANK
    RANK --> MW
    MW -->|00-discovery.json| S1
    S1 --> S1B --> S6

    style DISCOVERY fill:#e8f4fd
    style DOWNSTREAM fill:#f0fff4