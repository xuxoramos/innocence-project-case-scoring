"""Unit tests for the case-record circumstance extractor (tabular step)."""

from __future__ import annotations

from risk_engine.models import Case, Document, FlagCategory
from risk_engine.processing import default_pipeline


def _case_with(text: str) -> Case:
    case = Case(case_id="T", jurisdiction="j")
    case.documents.append(
        Document(doc_id="T1", case_id="T", needs_ocr=False, normalized_text=text)
    )
    return default_pipeline(ocr=False).process(case)


def _flag(case: Case, category: FlagCategory):
    return next((f for f in case.flags if f.category is category), None)


def test_passage_is_sentence_not_just_term():
    case = _case_with(
        "The jury convicted him. The sole eyewitness identified the defendant at trial. "
        "He appealed."
    )
    flag = _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE)
    assert flag is not None
    # The passage is the whole sentence, not the bare matched term.
    assert "sole eyewitness" in flag.source_passage
    assert flag.source_passage.startswith("The sole eyewitness identified")
    assert flag.source_passage.endswith("at trial.")


def test_weak_term_is_suppressed():
    case = _case_with("The defendant accepted a plea deal and was sentenced.")
    # "plea deal" (0.5) is below the confidence floor -> feature recorded, no flag.
    assert _flag(case, FlagCategory.INFORMANT_CIRCUMSTANCE) is None
    assert case.features["informant"] == 0


def test_word_boundary_prevents_partial_match():
    # "single witness" must not fire inside the plural "single witnesses".
    case = _case_with("The single witnesses both testified for the state.")
    assert _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE) is None


def test_strongest_term_in_category_wins():
    case = _case_with(
        "A rape kit was collected. The untested rape kit was never sent to the lab."
    )
    flag = _flag(case, FlagCategory.EVIDENCE_PRESERVATION)
    assert flag is not None
    # Picks the strong "untested rape kit" (0.85), not bare "rape kit" (0.5).
    assert flag.extraction_confidence >= 0.8
    assert "untested rape kit" in flag.source_passage


def test_paraphrase_lifts_recall():
    # Appellate phrasing a bare literal seed would have missed.
    case = _case_with("The conviction rested on a cooperating witness who recanted.")
    assert _flag(case, FlagCategory.INFORMANT_CIRCUMSTANCE) is not None
    assert _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE) is not None


def test_case_record_flags_carry_no_verification_source():
    # Directly-observable case-record categories verify against the record itself.
    case = _case_with("The sole eyewitness recanted years later.")
    flag = _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE)
    assert flag is not None and flag.verification_source is None


def test_misconduct_circumstances_flag_per_role():
    case = _case_with(
        "The opinion found a Brady violation by the prosecutor. "
        "Police had planted evidence at the scene. "
        "The analyst fabricated test results, and judicial misconduct tainted the trial."
    )
    for category in (
        FlagCategory.PROSECUTOR_MISCONDUCT,
        FlagCategory.POLICE_MISCONDUCT,
        FlagCategory.EXPERT_WITNESS_MISCONDUCT,
        FlagCategory.JUDICIAL_MISCONDUCT,
    ):
        flag = _flag(case, category)
        assert flag is not None, category
        # Text-detected misconduct describes the record; the registry supplies names.
        assert flag.verification_source is None


def test_misconduct_type_descriptor_brady_is_aggravating():
    case = _case_with("The opinion found the prosecutor withheld exculpatory evidence.")
    flag = _flag(case, FlagCategory.PROSECUTOR_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "concealing exculpatory evidence (Brady)"
    assert "aggravating" in flag.descriptors["type_gravity"]


def test_misconduct_type_descriptor_fabrication():
    case = _case_with("Police had planted evidence at the crime scene.")
    flag = _flag(case, FlagCategory.POLICE_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "fabricating evidence"
    assert "aggravating" in flag.descriptors["type_gravity"]


def test_improper_argument_ranks_lesser_than_fabrication():
    case = _case_with("The prosecutor made an improper closing argument to the jury.")
    flag = _flag(case, FlagCategory.PROSECUTOR_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "improper argument at trial"
    assert "lesser" in flag.descriptors["type_gravity"]


def test_non_misconduct_flag_carries_no_type_descriptor():
    case = _case_with("The sole eyewitness recanted years later.")
    flag = _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE)
    assert flag is not None
    assert "misconduct_type" not in flag.descriptors


def test_brady_material_synonym_maps_to_brady():
    # Corpus phrasing "suppressed Brady material" the bare "brady violation" seed missed.
    case = _case_with("The prosecution wrongfully suppressed Brady material at trial.")
    flag = _flag(case, FlagCategory.PROSECUTOR_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "concealing exculpatory evidence (Brady)"


def test_giglio_synonym_maps_to_brady():
    case = _case_with("The State violated Giglio by hiding the witness's deal.")
    flag = _flag(case, FlagCategory.PROSECUTOR_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "concealing exculpatory evidence (Brady)"


def test_failed_to_correct_false_testimony_maps_to_perjury():
    case = _case_with("The prosecutor failed to correct false testimony from the witness.")
    flag = _flag(case, FlagCategory.PROSECUTOR_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "perjury / false accusation"


def test_manufactured_evidence_synonym_maps_to_fabrication():
    case = _case_with("Officers manufactured evidence to secure the arrest.")
    flag = _flag(case, FlagCategory.POLICE_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "fabricating evidence"


def test_coerced_statement_synonym_maps_to_interrogation():
    # Only the interrogation synonym present, so it drives the descriptor.
    case = _case_with("Detectives took a coerced statement from the suspect overnight.")
    flag = _flag(case, FlagCategory.POLICE_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "misconduct in interrogations"


def test_perjured_testimony_flags_informant_without_type_descriptor():
    # Perjury/false-accusation lives on the informant column and stays a
    # circumstance flag -> detected, but no misconduct_type descriptor.
    case = _case_with("The conviction rested on perjured testimony from a key witness.")
    flag = _flag(case, FlagCategory.INFORMANT_CIRCUMSTANCE)
    assert flag is not None
    assert "misconduct_type" not in flag.descriptors


def test_windowed_rule_flags_informant_without_a_fixed_phrase():
    # No fixed informant phrase here, but "snitch" + "leniency"/"testimony"
    # co-occur within the window (spec v3 item 1), so the rule fires.
    case = _case_with("A snitch was promised leniency for his testimony.")
    flag = _flag(case, FlagCategory.INFORMANT_CIRCUMSTANCE)
    assert flag is not None
    assert flag.extraction_confidence >= 0.7
    assert flag.verification_source is None


def test_windowed_rule_needs_anchor_and_modifier_together():
    # Anchor present but no assertive modifier nearby -> no flag (no bare-token
    # false positive).
    case = _case_with("The informant lived quietly in the same neighborhood.")
    assert _flag(case, FlagCategory.INFORMANT_CIRCUMSTANCE) is None
    assert case.features["informant"] == 0


def test_batson_phrase_maps_to_batson_type():
    case = _case_with("The appellate court found a Batson violation in jury selection.")
    flag = _flag(case, FlagCategory.PROSECUTOR_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "racial jury exclusion (Batson)"


def test_batson_windowed_peremptory_strikes_by_race():
    case = _case_with(
        "The prosecutor used peremptory strikes to remove Black jurors because of race."
    )
    flag = _flag(case, FlagCategory.PROSECUTOR_MISCONDUCT)
    assert flag is not None
    assert flag.descriptors["misconduct_type"] == "racial jury exclusion (Batson)"


def test_single_witness_windowed_flags_witness_id():
    case = _case_with("The verdict turned on a lone identification made months later.")
    assert _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE) is not None


def test_vulnerable_defendant_minor_interrogation_circumstance():
    case = _case_with(
        "A 16-year-old juvenile was interrogated for nine hours without a parent present."
    )
    flag = _flag(case, FlagCategory.VULNERABLE_DEFENDANT_CIRCUMSTANCE)
    assert flag is not None
    # Circumstance only: checkable record facts, no verification source, and it
    # never asserts the confession was false.
    assert flag.verification_source is None
    assert "misconduct_type" not in flag.descriptors


def test_vulnerable_defendant_prolonged_interrogation_windowed():
    case = _case_with("The minor confessed after a prolonged interrogation overnight.")
    assert _flag(case, FlagCategory.VULNERABLE_DEFENDANT_CIRCUMSTANCE) is not None



