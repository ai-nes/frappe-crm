# Flow hiện tại: Lead, Student và AI-CRM

Tài liệu này mô tả mô hình backend hiện tại sau khi chuyển `CRM Student` thành
aggregate chính. `CRM Lead` chỉ giữ dữ liệu intake thô, provenance và các adapter
legacy cần thiết cho dữ liệu cũ.

## 1. Flow nghiệp vụ tổng quát

```mermaid
flowchart TD
    SOURCE["Facebook / Form / Import / Sale"] --> LEAD["CRM Lead<br/>Raw intake: tên, điện thoại, email, nguồn"]
    LEAD --> LEAD_API["Lead intake APIs<br/>lead / mapping / intake"]
    LEAD_API --> LEAD

    LEAD --> CONVERSION{"Đã đủ điều kiện chuyển đổi?"}
    CONVERSION -- "Chưa" --> RAW["Tiếp tục ở raw intake<br/>Lead processing / review"]
    CONVERSION -- "Rồi" --> HANDOFF["Lead → Student handoff<br/>student_conversion / contact_conversion"]
    HANDOFF --> STUDENT["CRM Student<br/>Canonical full profile + operational state"]
    LEAD -. "source_lead / converted_student<br/>provenance, không phải source of truth" .-> STUDENT

    subgraph STUDENT_DATA["Các nhóm dữ liệu thuộc Student"]
        GUARDIAN["CRM Student Guardian"]
        AUTHORITY["CRM Parent Contact Authority"]
        SCHOOL["CRM Student School"]
        ACADEMIC["CRM Student Academic Result / Assessment"]
        SCORE["CRM Score History / Score Signal"]
        INTERACTION["CRM Interaction / FCRM Note / Task"]
        OPERATIONS["Ownership / SLA / Lifecycle / Routing"]
    end

    STUDENT --> GUARDIAN
    STUDENT --> AUTHORITY
    STUDENT --> SCHOOL
    STUDENT --> ACADEMIC
    STUDENT --> SCORE
    STUDENT --> INTERACTION
    STUDENT --> OPERATIONS

    subgraph ADMISSION["Hồ sơ nhập học theo template"]
        PROFILE["CRM Student Admission Profile"]
        TEMPLATE["CRM Admission Profile Template"]
        JUNCTION["CRM Profile Template Document Type<br/>N:N + is_required + order_display"]
        DOC_TYPE["CRM Document Type"]
        DOCUMENT["CRM Student Document<br/>status / version / file / review"]
    end

    STUDENT --> PROFILE
    PROFILE --> TEMPLATE
    TEMPLATE --> JUNCTION
    JUNCTION --> DOC_TYPE
    STUDENT --> DOCUMENT
    PROFILE --> DOCUMENT
    DOC_TYPE --> DOCUMENT

    DASHBOARD["dashboard-crm<br/>Student Detail"] --> STUDENT_API["Student APIs<br/>profile / admission / school / activity"]
    STUDENT_API --> STUDENT
    STUDENT_API --> ADMISSION
    STUDENT --> OFFERING["CRM Admission Offering<br/>admission_method + education context"]
    OFFERING --> APPLICATION["CRM Admission Application"]
    APPLICATION --> MATERIALIZE["Create/reuse profile<br/>select Active template"]
    MATERIALIZE --> PROFILE
    MATERIALIZE --> CHECKLIST["Checklist from template junction<br/>is_required + order_display"]
    CHECKLIST --> DASHBOARD

    AI["AI-CRM"] --> AI_CONTEXT["Student profile context<br/>Student + related doctypes"]
    AI_CONTEXT --> STUDENT_API
    AI --> NBA["NBA / student_decision API"]
    NBA --> STUDENT
    AI --> INSIGHT["upsert_ai_insight API"]
    INSIGHT --> AI_RECORD["CRM AI Student Insight<br/>student = CRM Student"]
    AI --> INTERACTION_API["interaction intake / read APIs"]
    INTERACTION_API --> INTERACTION

    classDef raw fill:#fff3cd,stroke:#d39e00,color:#5c4500;
    classDef canonical fill:#d1ecf1,stroke:#0c7489,color:#063b47;
    classDef admission fill:#e2d9f3,stroke:#6f42c1,color:#32165e;
    classDef ai fill:#d4edda,stroke:#218838,color:#0d3b18;
    class LEAD,LEAD_API,RAW raw;
    class STUDENT,GUARDIAN,AUTHORITY,SCHOOL,ACADEMIC,SCORE,INTERACTION,OPERATIONS canonical;
    class PROFILE,TEMPLATE,JUNCTION,DOC_TYPE,DOCUMENT admission;
    class AI,AI_CONTEXT,NBA,INSIGHT,AI_RECORD,INTERACTION_API ai;
```

## 2. ERD quan hệ chính

```mermaid
erDiagram
    CRM_LEAD ||--o| CRM_STUDENT : "source_lead / converted_student"
    CRM_STUDENT ||--o{ CRM_STUDENT_ADMISSION_PROFILE : "has profiles"
    CRM_ADMISSION_PROFILE_TEMPLATE ||--o{ CRM_STUDENT_ADMISSION_PROFILE : "applies to"
    CRM_ADMISSION_PROFILE_TEMPLATE ||--o{ CRM_PROFILE_TEMPLATE_DOCUMENT_TYPE : "defines"
    CRM_DOCUMENT_TYPE ||--o{ CRM_PROFILE_TEMPLATE_DOCUMENT_TYPE : "belongs to templates"
    CRM_STUDENT ||--o{ CRM_STUDENT_DOCUMENT : "owns"
    CRM_STUDENT_ADMISSION_PROFILE ||--o{ CRM_STUDENT_DOCUMENT : "contains"
    CRM_DOCUMENT_TYPE ||--o{ CRM_STUDENT_DOCUMENT : "describes"

    CRM_STUDENT ||--o{ CRM_STUDENT_GUARDIAN : "has guardians"
    CRM_STUDENT ||--o{ CRM_PARENT_CONTACT_AUTHORITY : "governs contact authority"
    CRM_STUDENT ||--o{ CRM_STUDENT_SCHOOL : "has school history"
    CRM_STUDENT ||--o{ CRM_STUDENT_ACADEMIC_RESULT : "has academic results"
    CRM_STUDENT ||--o{ CRM_STUDENT_ASSESSMENT : "has assessments"
    CRM_STUDENT ||--o{ CRM_SCORE_HISTORY : "has score history"
    CRM_STUDENT ||--o{ CRM_INTERACTION : "has interactions"
    CRM_STUDENT ||--o{ CRM_STUDENT_ANALYSIS_RUN : "has analysis runs"
    CRM_STUDENT ||--o{ CRM_STUDENT_COMMAND_RECEIPT : "owns command receipts"

    CRM_LEAD ||--o{ CRM_STUDENT_CONTACT_CONVERSION : "legacy conversion source"
    CRM_STUDENT ||--o{ CRM_STUDENT_CONTACT_CONVERSION : "conversion target"
```

`CRM_PROFILE_TEMPLATE_DOCUMENT_TYPE` là bảng junction của quan hệ N:N giữa
`CRM Admission Profile Template` và `CRM Document Type`. Các thuộc tính nghiệp vụ
của từng loại hồ sơ nằm tại junction, gồm `is_required`, `requirement_mode`,
`min_required`, `quantity`, `order_display` và hướng dẫn hiển thị.

## 3. Flow AI-CRM trên Student profile

```mermaid
flowchart LR
    AI["AI-CRM"] --> REQUEST["studentId + payload AI"]
    REQUEST --> VALIDATE{"studentId là CRM Student?"}
    VALIDATE -- "Không" --> REJECT["Reject<br/>Không phân tích raw Lead"]
    VALIDATE -- "Có" --> LOAD["Lock CRM Student<br/>Đọc student_context_revision"]
    LOAD --> REVISION{"expected revision còn mới?"}
    REVISION -- "Không" --> STALE["Stale response<br/>Không ghi đè dữ liệu mới"]
    REVISION -- "Có" --> ANALYZE["NBA / phân tích hội thoại"]
    ANALYZE --> WRITE_INSIGHT["CRM AI Student Insight<br/>student = Student"]
    ANALYZE --> WRITE_INTERACTION["CRM Interaction / Analysis Run"]
    ANALYZE --> ACTION["student_decision / Task<br/>Nếu AI đề xuất hành động"]
    WRITE_INSIGHT --> STUDENT["CRM Student profile"]
    WRITE_INTERACTION --> STUDENT
    ACTION --> STUDENT
```

Quy tắc quan trọng:

- AI-CRM chỉ cần làm việc với `CRM Student` canonical.
- `CRM AI Student Insight` là projection AI chính của `CRM Student`; field `student`
  là liên kết canonical bắt buộc về Student.
- `CRM Lead` chỉ còn xuất hiện ở intake, provenance, conversion boundary và dữ liệu
  lịch sử. Một Lead chưa có Student canonical không được dùng để tạo insight hoặc
  interaction phân tích.
- `student_context_revision` trên Student dùng để chống AI ghi đè trên context đã
  thay đổi.

## Ý nghĩa khối Ownership / SLA / Lifecycle / Routing

Khối này là một nhóm logic trong flowchart, không phải một DocType duy nhất. Nó gom
bốn năng lực vận hành xoay quanh `CRM Student`:

- **Ownership:** xác định nhân viên/team đang phụ trách Student và lưu lịch sử thay
  đổi ownership.
- **SLA:** theo dõi hạn phản hồi, lần follow-up, trạng thái đúng hạn/quá hạn và
  escalation.
- **Lifecycle:** quản lý stage/status của Student cùng lý do và audit trail khi chuyển
  stage.
- **Routing:** chọn campus/team/pool/staff phù hợp để phân công Student theo rule,
  năng lực và phạm vi.

Mũi tên `CRM Student --> Ownership / SLA / Lifecycle / Routing` nghĩa là Student là
aggregate anchor và nguồn phân quyền; AI chỉ có thể đề xuất NBA, còn command thay đổi
ownership, SLA, lifecycle hoặc routing phải đi qua backend policy và actor được phép.

## 4. Admission application materialization

`CRM Admission Application` lấy `admission_method` từ `CRM Admission Offering`.
Khi application được tạo qua command API hoặc tạo trực tiếp bằng Frappe, backend
sẽ chọn template `Active` loại `academic_admission` theo phương thức xét và ưu tiên
template có `education_program` trùng với Student. Sau đó backend tạo hoặc reuse
`CRM Student Admission Profile` ở trạng thái `Draft` và trả checklist từ bảng
`CRM Profile Template Document Type`.

`admission_method` không bắt buộc ở raw intake. Nếu chưa xác định tại intake, workflow
sau chuyển đổi có thể cập nhật `CRM Student.admission_method` qua Student API; lúc tạo
application, Offering vẫn là nguồn xác thực cuối cùng. `CRM Student Document` chỉ
được tạo khi học sinh thực sự nộp file, không tạo placeholder cho mục checklist.
