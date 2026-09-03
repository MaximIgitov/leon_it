"""Комната интервью: старт, показ вопросов, запись ответов, секция кода.

``answer_text_for_evaluation`` — текст ответа для оценщика (транскрипт и код);
модуль оценки должен брать текст ответа через него, а не читать
``transcript_text`` напрямую, иначе код кандидата останется невидимым.
"""

from leonit.interviews.code import answer_text_for_evaluation

__all__ = ["answer_text_for_evaluation"]
