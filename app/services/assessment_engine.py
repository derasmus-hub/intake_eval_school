import json
import random
import yaml
from pathlib import Path
from openai import AsyncOpenAI
from app.config import settings
from app.models.assessment import (
    Bracket,
    PlacementQuestion,
    DiagnosticQuestion,
    PlacementAnswer,
    DiagnosticAnswer,
    PlacementResult,
    QuestionType,
)

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class AssessmentEngine:
    _instance = None
    _question_bank = None
    _analyzer_prompt = None
    _polish_struggles = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load_question_bank(self):
        if self._question_bank is None:
            with open(PROMPTS_DIR / "placement_questions.yaml", "r") as f:
                self._question_bank = yaml.safe_load(f)
        return self._question_bank

    def _load_analyzer_prompt(self):
        if self._analyzer_prompt is None:
            with open(PROMPTS_DIR / "assessment_analyzer.yaml", "r") as f:
                self._analyzer_prompt = yaml.safe_load(f)
        return self._analyzer_prompt

    def _load_polish_struggles(self):
        if self._polish_struggles is None:
            with open(PROMPTS_DIR / "polish_struggles.yaml", "r") as f:
                self._polish_struggles = yaml.safe_load(f)
        return self._polish_struggles

    def get_placement_questions(self) -> list[PlacementQuestion]:
        bank = self._load_question_bank()
        questions = []
        for q in bank["placement"]:
            questions.append(
                PlacementQuestion(
                    id=q["id"],
                    sentence=q["sentence"],
                    is_correct=q["is_correct"],
                    difficulty=q["difficulty"],
                    explanation=q["explanation"],
                )
            )
        return questions

    def score_placement(self, answers: list[PlacementAnswer]) -> PlacementResult:
        bank = self._load_question_bank()
        questions_by_id = {q["id"]: q for q in bank["placement"]}

        correct_count = 0
        max_correct_difficulty = 0

        for answer in answers:
            q = questions_by_id.get(answer.question_id)
            if q is None:
                continue
            if answer.answer == q["is_correct"]:
                correct_count += 1
                max_correct_difficulty = max(max_correct_difficulty, q["difficulty"])

        # Bracket determination:
        # Only got difficulty 1-2 correct = beginner
        # Got difficulty 1-3 correct = intermediate
        # Got difficulty 4+ correct = advanced
        if max_correct_difficulty <= 2:
            bracket = Bracket.BEGINNER
            detail = f"Correctly identified sentences up to difficulty {max_correct_difficulty}. Assigned to beginner diagnostic."
        elif max_correct_difficulty <= 3:
            bracket = Bracket.INTERMEDIATE
            detail = f"Correctly identified sentences up to difficulty {max_correct_difficulty}. Assigned to intermediate diagnostic."
        else:
            bracket = Bracket.ADVANCED
            detail = f"Correctly identified sentences up to difficulty {max_correct_difficulty}. Assigned to advanced diagnostic."

        return PlacementResult(
            bracket=bracket,
            score=correct_count,
            detail=detail,
        )

    def get_diagnostic_questions(self, bracket: Bracket) -> list[DiagnosticQuestion]:
        bank = self._load_question_bank()
        bracket_data = bank["diagnostic"][bracket.value]

        # Select 5 grammar, 4 vocabulary, 3 reading = 12 total
        grammar_pool = bracket_data["grammar"]
        vocab_pool = bracket_data["vocabulary"]
        reading_pool = bracket_data["reading"]

        grammar_qs = random.sample(grammar_pool, min(5, len(grammar_pool)))
        vocab_qs = random.sample(vocab_pool, min(4, len(vocab_pool)))
        reading_qs = random.sample(reading_pool, min(3, len(reading_pool)))

        questions = []
        for q in grammar_qs:
            questions.append(
                DiagnosticQuestion(
                    id=q["id"],
                    type=QuestionType.GRAMMAR_MCQ,
                    bracket=bracket,
                    question=q["question"],
                    options=q.get("options"),
                    correct_answer=q["correct_answer"],
                    skill="grammar",
                    topic=q["topic"],
                )
            )
        for q in vocab_qs:
            questions.append(
                DiagnosticQuestion(
                    id=q["id"],
                    type=QuestionType.VOCABULARY_FILL,
                    bracket=bracket,
                    question=q["question"],
                    correct_answer=q["correct_answer"],
                    skill="vocabulary",
                    topic=q["topic"],
                )
            )
        for q in reading_qs:
            questions.append(
                DiagnosticQuestion(
                    id=q["id"],
                    type=QuestionType.READING_COMPREHENSION,
                    bracket=bracket,
                    question=q["question"],
                    options=q.get("options"),
                    correct_answer=q["correct_answer"],
                    passage=q.get("passage"),
                    skill="reading",
                    topic=q["topic"],
                )
            )

        return questions

    def score_diagnostic_responses(
        self,
        answers: list[DiagnosticAnswer],
        questions: list[DiagnosticQuestion],
    ) -> dict:
        questions_by_id = {q.id: q for q in questions}

        results = {
            "grammar": {"correct": 0, "total": 0, "details": []},
            "vocabulary": {"correct": 0, "total": 0, "details": []},
            "reading": {"correct": 0, "total": 0, "details": []},
        }

        for answer in answers:
            q = questions_by_id.get(answer.question_id)
            if q is None:
                continue

            is_correct = answer.answer.strip().lower() == q.correct_answer.strip().lower()
            results[q.skill]["total"] += 1
            if is_correct:
                results[q.skill]["correct"] += 1

            results[q.skill]["details"].append(
                {
                    "question_id": q.id,
                    "question": q.question,
                    "student_answer": answer.answer,
                    "correct_answer": q.correct_answer,
                    "is_correct": is_correct,
                    "topic": q.topic,
                }
            )

        # Calculate percentages
        for skill in results:
            total = results[skill]["total"]
            correct = results[skill]["correct"]
            results[skill]["score"] = round((correct / total * 100) if total > 0 else 0, 1)

        total_correct = sum(r["correct"] for r in results.values())
        total_questions = sum(r["total"] for r in results.values())
        results["overall_score"] = round(
            (total_correct / total_questions * 100) if total_questions > 0 else 0, 1
        )

        return results

    async def analyze_with_ai(
        self,
        student_id: int,
        student_info: dict,
        bracket: Bracket,
        placement_score: int,
        diagnostic_scores: dict,
        questions: list[DiagnosticQuestion],
        answers: list[DiagnosticAnswer],
    ) -> dict:
        prompt_data = self._load_analyzer_prompt()
        polish_struggles = self._load_polish_struggles()

        # Build diagnostic responses text
        questions_by_id = {q.id: q for q in questions}
        responses_lines = []
        incorrect_lines = []

        for answer in answers:
            q = questions_by_id.get(answer.question_id)
            if q is None:
                continue
            is_correct = answer.answer.strip().lower() == q.correct_answer.strip().lower()
            status = "CORRECT" if is_correct else "INCORRECT"
            responses_lines.append(
                f"[{q.skill.upper()} - {q.topic}] Q: {q.question} | "
                f"Student answered: {answer.answer} | Correct: {q.correct_answer} | {status}"
            )
            if not is_correct:
                incorrect_lines.append(
                    f"- [{q.skill}/{q.topic}] Expected '{q.correct_answer}', "
                    f"got '{answer.answer}' — Question: {q.question}"
                )

        user_message = prompt_data["user_template"].format(
            student_id=student_id,
            name=student_info.get("name", "Unknown"),
            age=student_info.get("age", "Not specified"),
            bracket=bracket.value,
            placement_score=placement_score,
            diagnostic_responses="\n".join(responses_lines),
            grammar_score=f"{diagnostic_scores['grammar']['correct']}/{diagnostic_scores['grammar']['total']} ({diagnostic_scores['grammar']['score']}%)",
            vocab_score=f"{diagnostic_scores['vocabulary']['correct']}/{diagnostic_scores['vocabulary']['total']} ({diagnostic_scores['vocabulary']['score']}%)",
            reading_score=f"{diagnostic_scores['reading']['correct']}/{diagnostic_scores['reading']['total']} ({diagnostic_scores['reading']['score']}%)",
            overall_score=f"{diagnostic_scores['overall_score']}%",
            incorrect_details="\n".join(incorrect_lines) if incorrect_lines else "No incorrect answers.",
            polish_struggles=yaml.dump(
                polish_struggles, default_flow_style=False, allow_unicode=True
            ),
        )

        client = AsyncOpenAI(api_key=settings.api_key)

        response = await client.chat.completions.create(
            model=settings.model_name,
            messages=[
                {"role": "system", "content": prompt_data["system_prompt"]},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        result_text = response.choices[0].message.content
        return json.loads(result_text)


# Module-level singleton
assessment_engine = AssessmentEngine()
