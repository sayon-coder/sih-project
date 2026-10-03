# PIC/S Guidance PI 041-1 Summary
## Good Practices for Data Management and Integrity in Regulated GMP/GDP Environments

---

## 1. Executive Overview
The **PIC/S Guidance PI 041-1** serves as a non-mandatory guidance document for regulatory inspectorates and pharmaceutical organizations. It establishes a comprehensive, risk-based framework for data management and integrity across the entire lifecycle of Active Pharmaceutical Ingredients (APIs) and medicinal products.

---

## 2. Core Data Integrity Principles (ALCOA+)

Data integrity principles apply to all data formats—paper, electronic, and hybrid. The guidance builds upon the **ALCOA+** framework:

| Principle | Description |
| :--- | :--- |
| **Attributable** | All data creation, modification, or deletion must be traceable to the person or automated system responsible, complete with date/time stamps. |
| **Legible** | Records must remain readable, clean, and clear throughout their retention period. |
| **Contemporaneous** | Documentation must occur at the exact moment the activity or measurement takes place. |
| **Original** | The primary record, raw data capture, or a validated "True Copy" retaining all original metadata. |
| **Accurate** | Records must be precise, error-free, truthful, and verified by calibrated equipment and qualified staff. |
| **Complete** | Includes all raw data, secondary processing runs, metadata, and context necessary to reconstruct an event. |
| **Consistent** | Data must be handled according to defined, repeatable procedures and maintain sequential, chronological alignment. |
| **Enduring** | Stored on durable media designed to survive environmental risks across the required retention lifecycle. |
| **Available** | Readily accessible for review, audits, inspections, or product release decisions when needed. |

---

## 3. Data Governance Framework & Quality Culture

### Data Governance Framework
- Must be integrated into the organization's **Pharmaceutical Quality System (PQS)**.
- Needs clearly defined roles for data ownership, system administration, and technical oversight.
- Must establish mechanisms to detect, prevent, and correct data integrity failures.

### Risk Management Approach
- **Data Criticality**: Evaluates the potential impact of data loss or alteration on product safety, efficacy, and quality.
- **Data Risk**: Assesses vulnerabilities inherent to the system (e.g., degree of automation, ease of record alteration, subjective vs. objective measurement).

### Organizational Culture & Leadership
- Senior management must establish an open, constructive quality culture.
- Staff must be encouraged to report errors and deviations without fear of punitive action.
- Management must allocate sufficient resources for hardware, system validation, GDocP training, and oversight.

---

## 4. System-Specific Controls

### A. Paper-Based Systems
* **Template Control**: Worksheets, logbooks, and batch records must be version-controlled, uniquely numbered, issued, and reconciled to prevent unauthorized replacement forms.
* **Good Documentation Practices**: Entries must be filled contemporaneously using indelible ink. Corrections require a single line-through, date, initials, and an explanation if critical data is altered.
* **Secondary Verification**: Critical entries or manual calculations require a prompt, independent check by a second qualified individual.
* **Archival**: Physical records must be protected from loss, unauthorized access, and environmental hazards (fire, humidity, water damage).

### B. Computerised Systems
* **Access Control**:
  * Shared or generic accounts are strictly prohibited.
  * System Administrator functions must be segregated from routine operational roles.
  * Enforce strong password policies and role-based access limits.
* **Audit Trails**:
  * Automated, time-stamped audit trails must capture data creation, changes, and deletions.
  * Audit trails must be locked and active at all times.
  * Critical audit trails must be regularly reviewed prior to batch release.
* **System Clocks**: Clocks across network instruments and computer systems must be synchronized to ensure accurate sequence recording.
* **Backups & Recovery**: Regular, validated electronic backups capturing raw data, metadata, and audit trails must be executed and periodically tested for restoration.

### C. Hybrid Systems
* The use of hybrid systems (e.g., electronic instrument linked to a manual paper printout) is discouraged due to inherently high risk.
* Where used, robust procedural and technical controls must clearly define which record constitutes the official raw data.

---

## 5. Outsourced Activities & Supply Chain Oversight

* **Quality Agreements**: Technical and quality contracts must explicitly define responsibilities regarding data management, generation of true copies, and immediate notification of data integrity breaches.
* **Vendor Assurance**: Contract givers must perform risk-based audits and periodic reviews of contract facilities rather than relying solely on certificates of analysis (CoAs) or remote questionnaires.
* **True Copies**: Scanned paper or migrated digital records must capture all original content and metadata, verified through a documented process before original paper files are destroyed.