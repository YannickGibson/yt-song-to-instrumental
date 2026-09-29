# Automatic Short source screening

Short eligibility is a heuristic, not a content-safety certification. The detector
cannot recognize dangerous imagery or guarantee platform policy compliance.

The same entry point screens both the original source and alternate candidates:

1. Reject raw titles advertising audio, visualizers/visualisers, lyrics, trailers,
   teasers, snippets, concerts or live performances.
2. Decode the **entire source once** at four grayscale samples per second,
   160 by 90 pixels. Reuse these frames for clip motion and full-source checks.
3. Compare normalized 32 by 18 fingerprints at every period from three seconds
   through half the source duration. A one-sample alignment tolerance handles
   fractional periods. Require correlated matches throughout all four quarters
   of the overlap, substantial coverage, and a peak over background similarity.
   Repeated shots alone do not establish a looping source.
4. Reject fixed-layout/low-diversity footage even if effects create motion.
5. Missing, invalid, truncated, over-limit or timed-out analysis means **skip**,
   not approval. Sources over ten minutes are not automatically screened.

Limits and thresholds live in `constants.py`. The decoder has a ten-minute
wall-clock deadline and two decoder threads; the duration probe has twenty
seconds. Sample storage is bounded. Repetition work is O(N * L * P), with fixed
fingerprint size P, N sampled frames and L tested offsets. Searching up to half
the source is quadratic in N before the explicit duration cap; no full pairwise
similarity matrix is stored. Download cost is separate.

These checks do not establish uploader authenticity and are not semantic
moderation. A real music video can still contain unsafe footage. Short sources
should remain constrained by the configured source/channel policy. No new
manual-approval service, external model, or automatic upload is introduced by
this detector change.

Tests cover long multi-scene loops, brightness changes, intros/outros, isolated
repeated shots, unrelated changing scenes and failed/partial decoding. Real
media evaluations must stay in ignored local storage, never public fixtures.
