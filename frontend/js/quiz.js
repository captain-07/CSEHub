/**
 * The "Quiz me" widget on an article page.
 *
 * Stateless by design: the server hands back up to five randomly ordered
 * questions, the reader answers them one at a time, and one POST returns a
 * score. Nothing is stored, so there is no "already taken" state, no login gate
 * and no retry limit. Clicking "Try again" fetches a fresh set, which is what
 * makes the order change between attempts.
 */

import { friendlyError } from './api.js';
import { getArticleQuiz, submitArticleQuiz } from './api/articles.js';
import { escapeHtml } from './renderer.js';

// A fetch or grading response can land after the dialog has closed or a retry
// has started. This token lets those paths discard stale work.
let quizGeneration = 0;

// The attempt currently rendered in the dialog. Null while loading, closed, or
// after an error. There is only one quiz per article page.
let quizState = null;

/**
 * @param {HTMLElement} shell  the article shell the CTA was rendered into
 * @param {object} article     the article payload from the detail endpoint
 */
export function initQuiz(shell, article) {
  const section = shell.querySelector('#article-quiz');
  const start = section?.querySelector('#quiz-start');
  const modal = shell.querySelector('#quiz-modal');
  const panel = modal?.querySelector('#quiz-panel');
  const subtitle = modal?.querySelector('#quiz-modal-subtitle');
  if (!section || !start || !modal || !panel) return;

  if (subtitle) subtitle.textContent = article.title || '';

  const closeQuiz = () => {
    if (modal.open) modal.close();
  };

  start.addEventListener('click', () => {
    if (modal.open) return;
    modal.showModal();
    document.body.classList.add('quiz-open');
    loadQuiz(panel, article);
  });

  // Escape and every close button end up here, so the reset happens once.
  modal.addEventListener('close', () => {
    quizGeneration += 1;
    quizState = null;
    document.body.classList.remove('quiz-open');
    panel.innerHTML = '';
    if (start.isConnected) start.focus();
  });

  // Delegated so the listeners survive the panel being replaced by a step,
  // a result, or an error.
  modal.addEventListener('click', (event) => {
    const action = event.target.closest('[data-quiz-action]');
    if (action) {
      const kind = action.dataset.quizAction;
      if (kind === 'cancel') {
        closeQuiz();
      } else if (kind === 'retry') {
        loadQuiz(panel, article);
      } else if (kind === 'previous') {
        goToPreviousQuestion();
      } else if (kind === 'next') {
        goToNextQuestion();
      }
      return;
    }

    // A click on the backdrop targets the dialog element itself.
    if (event.target === modal) closeQuiz();
  });

  panel.addEventListener('submit', (event) => {
    event.preventDefault();
    gradeQuiz();
  });

  panel.addEventListener('change', () => {
    if (quizState?.grading) return;
    saveCurrentAnswer();
    syncActions();
    const error = panel.querySelector('[data-quiz-error]');
    if (error) error.textContent = '';
  });
}

/** Fetch a fresh random set and open on the first question. */
async function loadQuiz(panel, article) {
  const generation = ++quizGeneration;
  quizState = null;
  panel.scrollTop = 0;
  panel.innerHTML = '<div class="loading"><span class="loading-spinner"></span>Loading quiz…</div>';

  try {
    const payload = await getArticleQuiz(article.slug || article.id);
    if (generation !== quizGeneration) return;

    const questions = Array.isArray(payload?.questions) ? payload.questions : [];
    if (!questions.length) {
      panel.innerHTML = `
        <p class="quiz-empty" role="status">
          No quiz questions are available for this article yet.
        </p>
        <button class="button button-secondary" type="button" data-quiz-action="cancel">Close</button>`;
      return;
    }

    quizState = {
      panel,
      article,
      questions,
      index: 0,
      answers: new Map(),
      grading: false,
    };
    renderQuestion();
  } catch (error) {
    if (generation !== quizGeneration) return;
    console.error('Failed to load quiz', error);
    panel.innerHTML = `
      <p class="quiz-error" role="alert">${escapeHtml(friendlyError(error))}</p>
      <div class="quiz-actions">
        <button class="button button-primary" type="button" data-quiz-action="retry">Try again</button>
        <button class="button button-secondary" type="button" data-quiz-action="cancel">Close</button>
      </div>`;
  }
}

/** Render the current question, its saved answer, and the step controls. */
function renderQuestion(errorMessage = '') {
  if (!quizState) return;

  const { panel, questions, index, answers } = quizState;
  const question = questions[index];
  const selected = answers.get(question.id);
  const total = questions.length;
  const progress = ((index + 1) / total) * 100;

  panel.innerHTML = `
    <form class="quiz-form" novalidate>
      <div class="quiz-progress-wrap">
        <p class="quiz-progress" data-quiz-progress role="status" aria-live="polite">
          Question ${index + 1} of ${total}
        </p>
        <div
          class="quiz-progress-track"
          role="progressbar"
          aria-label="Quiz progress"
          aria-valuemin="1"
          aria-valuemax="${total}"
          aria-valuenow="${index + 1}"
          aria-valuetext="Question ${index + 1} of ${total}"
        >
          <span class="quiz-progress-fill" style="width: ${progress}%"></span>
        </div>
      </div>

      ${questionMarkup(question, index, selected)}

      <p class="quiz-form-error" data-quiz-error role="alert">${escapeHtml(errorMessage)}</p>
      <div class="quiz-actions">
        ${index > 0
          ? '<button class="button button-secondary" type="button" data-quiz-action="previous">Previous</button>'
          : ''}
        ${index < total - 1
          ? '<button class="button button-primary" type="button" data-quiz-action="next">Next</button>'
          : '<button class="button button-primary" type="submit" data-quiz-submit>See score</button>'}
        <button class="button button-secondary" type="button" data-quiz-action="cancel">Cancel</button>
      </div>
    </form>`;

  panel.scrollTop = 0;
  syncActions();

  const target = panel.querySelector('input[name="quiz-option"]:checked')
    || panel.querySelector('input[name="quiz-option"]');
  target?.focus({ preventScroll: true });
}

function questionMarkup(question, index, selectedOptionId) {
  const id = Number(question.id);
  const options = Array.isArray(question.options) ? question.options : [];
  return `
    <fieldset class="quiz-question" data-question-id="${id}">
      <legend class="quiz-question-prompt">
        <span class="quiz-question-number">${index + 1}.</span>
        <span class="quiz-question-text">${escapeHtml(question.prompt)}</span>
      </legend>
      <div class="quiz-options">
        ${options.map((option) => {
          const optionId = Number(option.id);
          const checked = selectedOptionId === optionId ? ' checked' : '';
          return `
            <label class="quiz-option">
              <input type="radio" name="quiz-option" value="${optionId}"${checked} />
              <span class="quiz-option-text">${escapeHtml(option.text)}</span>
            </label>`;
        }).join('')}
      </div>
    </fieldset>`;
}

function currentAnswer() {
  if (!quizState) return null;
  const checked = quizState.panel.querySelector('input[name="quiz-option"]:checked');
  return checked ? Number(checked.value) : null;
}

function saveCurrentAnswer() {
  if (!quizState) return;
  const question = quizState.questions[quizState.index];
  if (!question) return;

  const value = currentAnswer();
  if (value === null) {
    quizState.answers.delete(question.id);
  } else {
    quizState.answers.set(question.id, value);
  }
}

function syncActions() {
  if (!quizState) return;
  const answered = currentAnswer() !== null;
  const busy = Boolean(quizState.grading);

  const next = quizState.panel.querySelector('[data-quiz-action="next"]');
  const previous = quizState.panel.querySelector('[data-quiz-action="previous"]');
  const submit = quizState.panel.querySelector('[data-quiz-submit]');
  if (next) next.disabled = busy || !answered;
  if (previous) previous.disabled = busy;
  if (submit) submit.disabled = busy || !answered;
}

function showError(message) {
  const error = quizState?.panel.querySelector('[data-quiz-error]');
  if (error) error.textContent = message;
}

function goToPreviousQuestion() {
  if (!quizState || quizState.grading || quizState.index === 0) return;
  saveCurrentAnswer();
  quizState.index -= 1;
  renderQuestion();
}

function goToNextQuestion() {
  if (!quizState || quizState.grading || quizState.index >= quizState.questions.length - 1) return;
  saveCurrentAnswer();

  if (currentAnswer() === null) {
    showError('Choose an answer before moving on.');
    return;
  }

  quizState.index += 1;
  renderQuestion();
}

/** Collect every saved answer, post it once, and show the result. */
async function gradeQuiz() {
  if (!quizState || quizState.grading || quizState.index !== quizState.questions.length - 1) return;
  saveCurrentAnswer();

  const { panel, article, questions, answers } = quizState;
  const payload = questions.map((question) => ({
    question_id: question.id,
    option_id: answers.get(question.id) ?? null,
  }));

  // Normally unreachable because Next and See score are disabled until the
  // current question is answered, but it keeps a forced submit from sending
  // nulls or grading an incomplete attempt.
  const missingIndex = payload.findIndex((answer) => answer.option_id === null);
  if (missingIndex !== -1) {
    quizState.index = missingIndex;
    renderQuestion('Choose an answer for this question before seeing your score.');
    return;
  }

  const error = panel.querySelector('[data-quiz-error]');
  if (error) error.textContent = '';

  const fieldset = panel.querySelector('.quiz-question');
  quizState.grading = true;
  syncActions();
  if (fieldset) fieldset.disabled = true;

  const submit = panel.querySelector('[data-quiz-submit]');
  const submitLabel = submit?.textContent || 'See score';
  if (submit) {
    submit.setAttribute('aria-busy', 'true');
    submit.textContent = 'Checking…';
  }

  const generation = quizGeneration;
  try {
    const result = await submitArticleQuiz(article.slug || article.id, payload);
    if (generation !== quizGeneration) return;
    renderResult(result);
  } catch (requestError) {
    if (generation !== quizGeneration) return;
    console.error('Failed to grade quiz', requestError);
    quizState.grading = false;
    if (fieldset) fieldset.disabled = false;
    if (error) error.textContent = friendlyError(requestError);
    if (submit) {
      submit.removeAttribute('aria-busy');
      submit.textContent = submitLabel;
    }
    syncActions();
  }
}

function renderResult(result) {
  if (!quizState) return;

  const { panel, questions } = quizState;
  const score = Number(result?.score) || 0;
  const total = Number(result?.total) || 0;
  const percent = Number(result?.percent) || 0;

  const byId = new Map(questions.map((question) => [Number(question.id), question]));
  const optionText = (question, optionId) => {
    const option = question?.options?.find((item) => Number(item.id) === Number(optionId));
    return option?.text || 'that option';
  };

  const review = (Array.isArray(result?.results) ? result.results : []).map((row) => {
    const question = byId.get(Number(row.question_id));
    const correct = Boolean(row.is_correct);
    const chosen = optionText(question, row.chosen_option_id);
    const answer = optionText(question, row.correct_option_id);
    return `
      <li class="quiz-result-item ${correct ? 'is-correct' : 'is-wrong'}">
        <p class="quiz-result-prompt">${escapeHtml(question?.prompt || `Question ${row.question_id}`)}</p>
        <p class="quiz-result-answer">
          <span class="quiz-result-verdict">${correct ? 'Correct.' : 'Not quite.'}</span>
          ${correct ? '' : `You chose “${escapeHtml(chosen)}”. `}
          The answer is “${escapeHtml(answer)}”.
        </p>
        ${row.explanation
          ? `<p class="quiz-result-explanation">${escapeHtml(row.explanation)}</p>`
          : ''}
      </li>`;
  }).join('');

  panel.innerHTML = `
    <div class="quiz-result">
      <h3 class="quiz-result-title" tabindex="-1">
        You scored ${score} / ${total} (${percent}%)
      </h3>
      <ul class="quiz-result-list">${review}</ul>
      <div class="quiz-actions">
        <button class="button button-primary" type="button" data-quiz-action="retry">Try again</button>
        <button class="button button-secondary" type="button" data-quiz-action="cancel">Close</button>
      </div>
    </div>`;

  panel.scrollTop = 0;
  panel.querySelector('.quiz-result-title')?.focus();
}
