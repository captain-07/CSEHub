"""The one rule that decides whether an article's body may be served.

Kept in this app rather than on `Article` so the article model never has to
import a payment concept, and so every content-bearing route — the detail
serializer, the quiz, the assistant, the conversation history and the PDF —
asks the same question instead of growing its own copy.
"""

from .models import Purchase

# One sentence for every 402, so a locked surface cannot drift in wording
# between the article viewset and the chatbot app.
PAID_ARTICLE_MESSAGE = (
    'This article is paid. Buy it to unlock the full text and its extras.'
)


def can_read_article(user, article):
    """Whether `user` may read the body of `article`.

    A free article is readable by anyone, including an anonymous visitor. A paid
    article is readable by:

    * anyone who holds a `paid` purchase for it;
    * staff — they set the price and their editor reads the same detail route
      that the reader does.

    Staff is an unconditional pass, not an author check: reads were already
    open to every staff member before articles could be sold, and the write
    path is separately scoped to the author by `IsAuthorOrReadOnly`.
    """
    if article is None:
        return False
    if not article.is_paid:
        return True
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_staff', False):
        return True
    return Purchase.objects.filter(
        user=user,
        article=article,
        status=Purchase.STATUS_PAID,
    ).exists()
