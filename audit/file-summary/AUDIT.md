# File summary — pre-code audit (2026-10-27, Agent BC1)

Project used for proof: `Test_3` (`4b7bfd50ddb6`). Canonical order is
`(capture_id, seq)`.

## Witness files

The query below identifies the requested witnesses without using the filename
to classify their content:

```sql
SELECT c.project_id,c.capture_id,c.kind,f.filename,f.source_path
FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id
WHERE c.capture_id IN ('44621571bccc','e84832b42679','289784700e72');
```

- HTTP DL: `44621571bccc`, kind `ue`, source
  `M1_FREE_DL-7Go_Max-10_W30_26Jun23_103320.4.nmf`.
- Voice: `e84832b42679`, kind `ue`, source
  `BCNE 26S24_VD_T_MESURE-BENCH-CENTRE-COMMERCIAL-PETITE-FORET_indoor_26Jun11_111346.8.nmf`.
- Scanner: `289784700e72`, kind `scanner`, source
  `M1_Ibflex-Scanner_All-LTE_26Jun23_103320.5.nmf`.

No RTT source exists in the corpus:

```sql
SELECT count(*) FILTER (WHERE event_code='RTT') rtt_rows,
       count(DISTINCT nmf_file_id) FILTER (WHERE event_code='RTT') rtt_files,
       count(*) FILTER (WHERE event_code='CAF') caf_rows,
       count(*) FILTER (WHERE event_code='CAD') cad_rows,
       count(*) FILTER (WHERE event_code='DAF') daf_rows
FROM stg_event_raw;
```

Output: `rtt_rows=0`, `rtt_files=0`, `caf_rows=0`, `cad_rows=57`,
`daf_rows=52`. Latency and call-setup failures therefore remain visible but
unavailable, with `no RTT in file` / `no CAF in file`.

## HTTP DL and radio split

The first command starts at `CMDREQ seq=301`, its transfer completes at
`DCOMP seq=1203`, and the terminal command completion is `CMDCOMP seq=1206`.
The file-summary window is therefore the proven CMDREQ→terminal-CMDCOMP
interval. The same rule is applied to every command in the capture.

```sql
WITH windows AS (
 SELECT t.capture_id,t.seq_start,
   (SELECT min(r.seq) FROM stg_event_raw r
    WHERE r.project_id=t.project_id AND r.capture_id=t.capture_id
      AND r.event_code='CMDCOMP' AND r.seq>t.seq_dcomp) seq_end
 FROM task_run t
 WHERE t.project_id='4b7bfd50ddb6' AND t.capture_id='44621571bccc'
   AND t.task_type='HTTP_DL' AND t.seq_daa IS NOT NULL AND t.seq_dcomp IS NOT NULL
), rates AS (
 SELECT r.event_code,r.system,NULLIF(r.raw_fields->>'c5','')::double precision bps
 FROM windows w JOIN stg_event_raw r
 ON r.project_id='4b7bfd50ddb6' AND r.capture_id=w.capture_id
 AND r.seq BETWEEN w.seq_start AND w.seq_end
 WHERE r.event_code IN ('PDCPRATED','PDCPRATEU','RLCRATE','RLCRATEU')
)
SELECT event_code,system,count(*) n,avg(bps)/1e6 mean_mbps,max(bps)/1e6 max_mbps
FROM rates WHERE bps IS NOT NULL GROUP BY event_code,system;
```

Output for the canonical PDCP split:

- `PDCPRATED / LTE`: `n=659`, mean `178.72880921092565 Mbit/s`, max
  `483.562709 Mbit/s`.
- `PDCPRATEU / LTE`: `n=187`, mean `0.394106 Mbit/s`, max
  `1.050611 Mbit/s`.
- No admissible NR row is present in these windows. NR is therefore `—`; it
  is not reconstructed from the total.

Application throughput comes from DRATE CSV column 7 (DL) and column 6 (UL):

```sql
-- same windows CTE
SELECT count(*) n,avg((r.raw_fields->>'c6')::double precision)/1e6 mean_mbps,
       max((r.raw_fields->>'c6')::double precision)/1e6 max_mbps
FROM windows w JOIN stg_event_raw r
  ON r.project_id='4b7bfd50ddb6' AND r.capture_id=w.capture_id
 AND r.seq BETWEEN w.seq_start AND w.seq_end
WHERE r.event_code='DRATE' AND r.raw_fields->>'c6' IS NOT NULL;
```

Output: `n=214`, mean `170.9819526401869 Mbit/s`, max
`456.421984 Mbit/s`.

## Voice, RACH, failures and scanner

- Voice witness content: `AQDL=50`, `CAA=10`, `CAC=24`, `CAD=10`.
- RACH failure numerator is the documented sum of RACHI preamble failures
  (CSV column 10) and contention-resolution failures (CSV column 12).
  Denominator is the documented RACHI preamble count (CSV column 9).
- Call setup fail is `CAF / CAA`, voice drop is `CAD / CAA`, and session
  fail is `DAF / DAA`. A denominator of zero means the test is absent (`—`),
  while a present denominator with no failure preserves real zero.
- Scanner witness events are `OFDMSCAN`, `CELLSCAN`, `GPS`, `MARK`,
  `SCANCONFIG`, `STARTSCAN`; it exposes only `Task = Scanner`.

