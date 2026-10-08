https://kafka2306.github.io/autonomous-vehicles/

# autonomous-vehicles

[![Quality](https://github.com/KAFKA2306/autonomous-vehicles/actions/workflows/quality.yml/badge.svg)](https://github.com/KAFKA2306/autonomous-vehicles/actions/workflows/quality.yml)
[![Government source check](https://github.com/KAFKA2306/autonomous-vehicles/actions/workflows/source-check.yml/badge.svg)](https://github.com/KAFKA2306/autonomous-vehicles/actions/workflows/source-check.yml)
[![Deploy Pages](https://github.com/KAFKA2306/autonomous-vehicles/actions/workflows/pages.yml/badge.svg)](https://github.com/KAFKA2306/autonomous-vehicles/actions/workflows/pages.yml)

Autonomous Vehicles のtesting activityとcrash-report evidenceを、California DMV / NHTSAの政府一次情報から再現可能に追跡します。

## Public dashboard

- latest California statewide public-road testing observation
- current California permit holder counts for testing with a safety driver / driverless testing / deployment
- NHTSA ADS report count and reporting-entity count
- explicit scope warnings: **testing ≠ deployment**, **report count ≠ safety rate**

現在のcanonical evidenceにcommercial driverless service area / rides / fleet sizeが存在しないため、Pagesは企業PR等からcurrent operation geographyを推測しません。

Pages artifactは巨大ledgerを複製せず、`summary.json`と`index.json`だけを公開projectionとして使います。

## Canonical views

- [`api/v1/autonomous-vehicles/summary.json`](api/v1/autonomous-vehicles/summary.json) — cross-repository / Pages向けcompact summary
- [`api/v1/autonomous-vehicles/index.json`](api/v1/autonomous-vehicles/index.json) — source and metric-boundary contract
- [`api/v1/autonomous-vehicles/nhtsa-sgo.json`](api/v1/autonomous-vehicles/nhtsa-sgo.json) — NHTSA SGO report ledger
- [`api/v1/autonomous-vehicles/california-dmv.json`](api/v1/autonomous-vehicles/california-dmv.json) — California DMV testing / disengagement / permit evidence

NHTSA viewはADS / Level 2 ADAS / Otherを分離し、Report IDごとのlatest Report Versionをderived viewへ採用します。Raw CSV revisionsは別保存し、訂正履歴を保持します。

California DMV viewはannual public-road testing miles、disengagement event、permit snapshotを保持します。`testing_miles_per_disengagement`は同一report year・同一Permit Numberで分子分母が整合する場合だけ生成し、**testing activityの運用指標**として扱います。安全率・安全順位ではありません。

Statewide observationとcompany-level CSVは別seriesです。より新しいstatewide aggregateから未取得のcompany-level valuesを推測しません。

California DMVの新しいAutonomous Vehicles regulationsは2026年4月28日に発効しました。従来のdisengagement reportingは廃止され、drivered testingはDynamic Driving Task Performance Relevant System Failures、driverless testingはvehicle immobilizationsへ移行します。新しいtesting reporting requirementsは発効120日後の2026年8月26日にoperativeとなります。過去のdisengagement seriesと新しいreporting metricは同じseriesとして連結せず、公開された実提出データを取得できるまではUNVERIFIEDとして扱います。

## Evidence

- NHTSA raw revisions: `data/nhtsa/sgo/revisions/<revision_id>/`
- California DMV raw revisions: `data/california/dmv/revisions/<revision_id>/`
- statewide testing observations / reporting regime boundary: [`data/california-dmv-testing.json`](data/california-dmv-testing.json)
- permit snapshot: [`data/california-dmv-permits.json`](data/california-dmv-permits.json)

source bytesのSHA-256からrevision identityを作るため、retrieval timeだけが変わった場合は新raw revisionを作りません。

## Update and verification

```bash
python src/update_av_evidence.py
python src/build_av_summary.py
```

- `Government source check` はPRでlive government sourceを検証し、main/weeklyではsource bytesが変化した場合だけevidence/viewsをcommitします。
- `Deploy Pages` はPRでsummary/indexのsemantic boundaryとdashboard JSを検証し、mainではsmall public projectionをdeployしてexact commit SHAを照合します。

## Primary sources

- NHTSA Standing General Order on Crash Reporting: https://www.nhtsa.gov/laws-regulations/standing-general-order-crash-reporting
- California DMV Autonomous Vehicles: https://www.dmv.ca.gov/portal/vehicle-industry-services/autonomous-vehicles/
- California DMV Permit Resources: https://www.dmv.ca.gov/portal/vehicle-industry-services/autonomous-vehicles/autonomous-vehicles-program-permit-resources/
- California DMV Rulemaking Actions: https://www.dmv.ca.gov/portal/about-the-california-department-of-motor-vehicles/california-dmv-rulemaking-actions/
- California DMV Adopted Regulatory Text, Article 3.7: https://www.dmv.ca.gov/portal/file/order-to-adopt-article-3-7-regulations-pdf/
- California DMV Final Statement of Reasons, OAL File Number 2025-0415-04: https://www.dmv.ca.gov/portal/file/final-statement-of-reasons-2025-0415-04-pdf/

## Data boundaries

- NHTSA report countはexposure-normalizedではない。matching mileage denominatorなしにcompany safety rateを作らない
- ADSとLevel 2 ADASを混ぜない
- `Same Incident ID`を保持し、report数とincident identityを区別する
- California DMV testingとdeploymentを混同しない
- 2026年4月28日のregulation change前後でdisengagement、Dynamic Driving Task Performance Relevant System Failures、vehicle immobilizationsを同一metricとして連結しない
- 新しいCalifornia DMV testing reporting requirementsは2026年8月26日からoperative。公開された実提出データが確認できるまで値を推測しない
- sourceにない値・期間・単位を補間しない

## Operational ontology

[Project ontology](ontology/project.yaml) connects canonical entities and relationships to source evidence, guarded actions and measurable outcomes under the [shared causal-evidence vocabulary](https://github.com/KAFKA2306/know/blob/main/ontology/causal-evidence-core.yaml). It documents the existing workflow's decision boundary without claiming a new execution engine or paid service.
