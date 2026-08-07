//==============================
// Node Constraints
//==============================

CREATE CONSTRAINT project_id_unique
IF NOT EXISTS
FOR (n:Project)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT drawing_set_id_unique
IF NOT EXISTS
FOR (n:DrawingSet)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT drawing_page_id_unique
IF NOT EXISTS
FOR (n:DrawingPage)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT drawing_block_id_unique
IF NOT EXISTS
FOR (n:DrawingBlock)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT table_id_unique
IF NOT EXISTS
FOR (n:Table)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT block_caption_id_unique
IF NOT EXISTS
FOR (n:BlockCaption)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT table_caption_id_unique
IF NOT EXISTS
FOR (n:TableCaption)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT cross_section_id_unique
IF NOT EXISTS
FOR (n:CrossSection)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT drawing_basic_info_id_unique
IF NOT EXISTS
FOR (n:DrawingBasicInfo)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT drawing_annotation_id_unique
IF NOT EXISTS
FOR (n:DrawingAnnotation)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT plain_text_id_unique
IF NOT EXISTS
FOR (n:PlainText)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT title_id_unique
IF NOT EXISTS
FOR (n:Title)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT ignored_element_id_unique
IF NOT EXISTS
FOR (n:IgnoredElement)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT import_batch_id_unique
IF NOT EXISTS
FOR (n:ImportBatch)
REQUIRE n.id IS UNIQUE;

//==============================
// Indexes
//==============================

CREATE INDEX drawing_page_number_index
IF NOT EXISTS
FOR (n:DrawingPage)
ON (n.page_number);

CREATE INDEX drawing_page_file_name_index
IF NOT EXISTS
FOR (n:DrawingPage)
ON (n.file_name);

CREATE INDEX drawing_set_name_index
IF NOT EXISTS
FOR (n:DrawingSet)
ON (n.name);

CREATE INDEX drawing_set_source_dir_index
IF NOT EXISTS
FOR (n:DrawingSet)
ON (n.source_dir);

CREATE INDEX import_batch_status_index
IF NOT EXISTS
FOR (n:ImportBatch)
ON (n.status);

CREATE INDEX import_batch_started_at_index
IF NOT EXISTS
FOR (n:ImportBatch)
ON (n.started_at);

//==============================
// Semantic Evidence Layer
//==============================

CREATE CONSTRAINT text_observation_id_unique
IF NOT EXISTS
FOR (n:TextObservation)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT block_interpretation_id_unique
IF NOT EXISTS
FOR (n:BlockInterpretation)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT basic_info_interpretation_id_unique
IF NOT EXISTS
FOR (n:BasicInfoInterpretation)
REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT table_interpretation_id_unique
IF NOT EXISTS
FOR (n:TableInterpretation)
REQUIRE n.id IS UNIQUE;

CREATE INDEX text_observation_page_id_index
IF NOT EXISTS
FOR (n:TextObservation)
ON (n.page_id);

CREATE INDEX text_observation_target_element_id_index
IF NOT EXISTS
FOR (n:TextObservation)
ON (n.target_element_id);

CREATE INDEX text_observation_recognition_run_id_index
IF NOT EXISTS
FOR (n:TextObservation)
ON (n.recognition_run_id);

CREATE INDEX text_observation_status_index
IF NOT EXISTS
FOR (n:TextObservation)
ON (n.status);

CREATE INDEX text_observation_cache_key_index
IF NOT EXISTS
FOR (n:TextObservation)
ON (n.cache_key);

CREATE INDEX block_interpretation_block_id_index
IF NOT EXISTS
FOR (n:BlockInterpretation)
ON (n.block_id);

CREATE INDEX block_interpretation_recognition_run_id_index
IF NOT EXISTS
FOR (n:BlockInterpretation)
ON (n.recognition_run_id);

CREATE INDEX block_interpretation_status_index
IF NOT EXISTS
FOR (n:BlockInterpretation)
ON (n.status);

CREATE INDEX block_interpretation_cache_key_index
IF NOT EXISTS
FOR (n:BlockInterpretation)
ON (n.cache_key);

CREATE INDEX basic_info_interpretation_basic_info_id_index
IF NOT EXISTS
FOR (n:BasicInfoInterpretation)
ON (n.basic_info_id);

CREATE INDEX basic_info_interpretation_recognition_run_id_index
IF NOT EXISTS
FOR (n:BasicInfoInterpretation)
ON (n.recognition_run_id);

CREATE INDEX basic_info_interpretation_status_index
IF NOT EXISTS
FOR (n:BasicInfoInterpretation)
ON (n.status);

CREATE INDEX table_interpretation_table_id_index
IF NOT EXISTS
FOR (n:TableInterpretation)
ON (n.table_id);

CREATE INDEX table_interpretation_recognition_run_id_index
IF NOT EXISTS
FOR (n:TableInterpretation)
ON (n.recognition_run_id);

CREATE INDEX table_interpretation_status_index
IF NOT EXISTS
FOR (n:TableInterpretation)
ON (n.status);
