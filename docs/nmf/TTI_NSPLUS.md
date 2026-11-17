# TTI_NSPLUS extension contract

`TTI_NSPLUS` is an NS+8 CSV extension carried inside an NMF file. It is not a
standard Nemo event. The authoritative producer is
`/home/devmat/nsplus/rust/qbt-core/src/nmf_writer.rs::tti_nsplus`.
BC4 activates this schema for the current NS+8/NMF 2.59 contract; obsolete
2.19 extension files remain explicitly unsupported.

```text
TTI_NSPLUS,time,,recState,frame_idx,sfn,subfn,carrier,rnti,mcs,prb,tbs,crc,harq_id,rv,rat
```

| CSV column | Field | Type | Unit / meaning |
|---:|---|---|---|
| 1 | event | string | `TTI_NSPLUS` |
| 2 | time | `HH:MM:SS.mmm` | producer observation time |
| 3 | context count | empty | zero Nemo contexts |
| 4 | recState | integer | producer radio-system code (`7` LTE; `12` reserved by the extension) |
| 5 | frame_idx | unsigned integer | source frame index |
| 6 | sfn | unsigned integer | system frame number from the decoded B173 record |
| 7 | subfn | unsigned integer | subframe index from the decoded B173 record |
| 8 | carrier | unsigned integer | serving carrier index |
| 9 | rnti | unsigned integer or empty | temporary radio-network identifier |
| 10 | mcs | unsigned integer or empty | PDSCH MCS index per transport block |
| 11 | prb | unsigned integer or empty | scheduled physical resource blocks |
| 12 | tbs | unsigned integer or empty | transport-block size in bytes |
| 13 | crc | `0` or `1` or empty | `1` CRC OK, `0` CRC failure |
| 14 | harq_id | unsigned integer or empty | HARQ process identifier |
| 15 | rv | unsigned integer or empty | redundancy version (`0..3`) |
| 16 | rat | quoted string | `LTE` today; `NR` reserved |

One line represents one decoded transport block. Two codewords in the same
subframe therefore produce two lines. This is sparse TTI evidence, not a
promise of 1,000 rows per second: BC4 never synthesizes missing subframes.

BC4 retains raw observations ordered by `(capture_id, seq)`. Graphs expose
their millisecond source timestamp. The measurements table keeps one raw row
per transport block instead of collapsing all TTI rows into a one-second row.
The project/capture temporal resolution may be set to `1ms`; bins remain
capture-local and never join or interpolate across captures.
