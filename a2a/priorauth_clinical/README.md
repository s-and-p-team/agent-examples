# Clinical Review

A agent in the **prior authorization** example. The scenario, the full topology
and the build/deploy instructions live in the example's main README:
[Prior Authorization](../priorauth_intake/README.md).

Reads the patient's encounters, medications and labs from the patient records service, looks the procedure and drug up in the medical coding service, and decides whether the request is clinically justified.

Replies `SUPPORTED`, `NOT SUPPORTED` or `MORE INFORMATION NEEDED` with a short reason.

All patient data in this example is synthetic.
