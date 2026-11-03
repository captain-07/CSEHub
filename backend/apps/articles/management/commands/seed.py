from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from apps.articles.models import (
    Category, Tag, Article, ArticleTag, CodeSnippet, QuizQuestion,
)


# Editor.js documents are verbose to write inline, so blocks are built from
# (type, data) pairs and expanded here. Every type used below must appear in
# SUPPORTED_BLOCK_TYPES (apps.articles.models) or the API rejects the article.
def document(*blocks):
    return {
        'time': 0,
        'version': '2.30.8',
        'blocks': [{'type': kind, 'data': data} for kind, data in blocks],
    }


def heading(text, level=2):
    return ('header', {'text': text, 'level': level})


def para(text):
    return ('paragraph', {'text': text})


def bullets(*items):
    return ('list', {'style': 'unordered', 'items': [{'content': item} for item in items]})


def steps(*items):
    return ('list', {'style': 'ordered', 'items': [{'content': item} for item in items]})


def code(language, body):
    return ('code', {'code': body, 'language': language})


def quote(text, caption=''):
    return ('quote', {'text': text, 'caption': caption})


def link(url, text):
    return ('linkTool', {'url': url, 'text': text})


DIVIDER = ('delimiter', {})


ARTICLES = [
    {
        'slug': 'binary-search-boundaries',
        'title': 'Binary Search and the Art of the Boundary',
        'excerpt': (
            'Binary search is easy to write and easy to get subtly wrong. Deriving '
            'the loop bounds once removes an entire family of off-by-one bugs.'
        ),
        'category': 'dsa',
        'tags': ['array', 'recursion'],
        'is_featured': True,
        'is_published': True,
        'content': document(
            heading('The idea'),
            para(
                'Binary search only works on data that is already sorted. It halves '
                'the search space on every comparison, so locating one element among '
                '<code>n</code> takes <code>O(log n)</code> comparisons — about 20 for a '
                'million elements.'
            ),
            para(
                'Most people remember it as <code>while lo &lt;= hi</code>. That form is '
                'correct, but it pushes you to reason about <code>hi + 1</code> and about '
                'what an empty range means. There is a cleaner formulation.'
            ),
            heading('The half-open interval'),
            para(
                'Keep the candidate range as <code>[lo, hi)</code> — <b>lo included, hi '
                'excluded</b>. The range is empty exactly when <code>lo == hi</code>, which '
                'is the single termination condition you need to remember.'
            ),
            code('python', '''def contains(sorted_items, target):
    lo, hi = 0, len(sorted_items)

    while lo < hi:
        mid = lo + (hi - lo) // 2
        value = sorted_items[mid]

        if value == target:
            return True
        if value < target:
            lo = mid + 1
        else:
            hi = mid

    return False'''),
            para(
                'Note <code>lo + (hi - lo) // 2</code> rather than <code>(lo + hi) // 2</code>. '
                'They agree in Python because integers are arbitrary precision, but the '
                'overflow-safe form is the one that stays correct in a language with fixed '
                'width integers.'
            ),
            heading('Why <code>lo = mid + 1</code> is not optional'),
            para(
                'When <code>sorted_items[mid] &lt; target</code> you know the answer is not at '
                '<code>mid</code>, so <code>mid</code> itself can be discarded. Leaving it in '
                'the range makes the loop shrink by one element per step on the low side — '
                'quadratic behaviour that looks correct on small inputs and times out on '
                'large ones.'
            ),
            quote(
                'A half-open range has exactly one empty state. Two closed bounds have two, '
                'and that is where the bugs live.',
                caption='The whole trick in one sentence',
            ),
            heading('Finding a boundary instead of a value'),
            para(
                'Most real problems are not "is this value present" but "where would it go". '
                'Counting how many elements are <code>&lt; target</code> is the same loop with '
                'no early exit, and it is what powers <code>bisect_left</code> in Python and '
                '<code>lower_bound</code> in C++.'
            ),
            code('python', '''def lower_bound(sorted_items, target):
    lo, hi = 0, len(sorted_items)

    while lo < hi:
        mid = lo + (hi - lo) // 2
        if sorted_items[mid] < target:
            lo = mid + 1
        else:
            hi = mid

    return lo'''),
            bullets(
                '<code>lower_bound(x)</code> — first index whose value is <code>&gt;= x</code>.',
                '<code>upper_bound(x)</code> — first index whose value is <code>&gt; x</code>.',
                '<code>contains(x)</code> is simply <code>lower_bound(x) &lt; n</code>.',
            ),
            DIVIDER,
            heading('Common mistakes'),
            bullets(
                'Rebuilding <code>hi</code> as <code>len(items) - 1</code> mid-loop, which silently '
                'changes the interval convention.',
                'Testing <code>lo &lt;= hi</code> in a half-open loop — it can never be false while '
                'the range is valid, so the loop is one comparison short of terminating.',
                'Forgetting that the array must be sorted, and assuming the input guarantees it.',
            ),
            para(
                'The full source of Python’s implementation, which is the same loop with the '
                'exposition stripped out, is worth reading once: ',
            ),
            link('https://github.com/python/cpython/blob/main/Modules/bisect.py', 'CPython Lib/bisect.py'),
        ),
    },
    {
        'slug': 'dynamic-programming-memoisation',
        'title': 'Dynamic Programming: Memoisation vs Tabulation',
        'excerpt': (
            'Recursion with a cache and bottom-up iteration solve the same problems. '
            'Choosing between them is about call-stack depth and wasted work, not taste.'
        ),
        'category': 'dsa',
        'tags': ['dp', 'recursion'],
        'is_featured': False,
        'is_published': True,
        'content': document(
            heading('What makes a problem suitable'),
            para(
                'Dynamic programming applies when a problem has two properties that are easy '
                'to check and easy to get wrong: <b>optimal substructure</b> (the best answer '
                'is built from the best answers to smaller instances) and <b>overlapping '
                'subproblems</b> (the same instance is solved over and over).'
            ),
            para(
                'Without overlap, you are not repeating work and memoisation buys you nothing. '
                'Without optimal substructure, a locally greedy choice is simply wrong.'
            ),
            heading('The fibonacci that made the case'),
            para(
                'Naive recursive fibonacci is exponential because each call spawns two more. '
                'Memoisation fixes it by making every state computed at most once.'
            ),
            code('python', '''from functools import cache


@cache
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)'''),
            para(
                'The call count drops from <code>O(φⁿ)</code> to <code>O(n)</code>. Note that '
                'the cached values include every <code>fib(k)</code> for <code>k &lt;= n</code>, '
                'because there is no way to compute <code>fib(n)</code> without them.'
            ),
            heading('Bottom-up, for when recursion is the wrong shape'),
            para(
                'Memoisation recursion depth is proportional to the size of the largest state, '
                'so a problem with a million-element dimension blows the Python call stack. '
                'Tabulation inverts the dependency order and removes the stack entirely.'
            ),
            code('python', '''def fib_iterative(n):
    if n < 2:
        return n

    previous, current = 0, 1
    for _ in range(2, n + 1):
        previous, current = current, previous + current

    return current'''),
            para(
                'Same <code>O(n)</code> time, <code>O(1)</code> space instead of <code>O(n)</code> '
                'for the cache, and no recursion limit to worry about. The two are not '
                'interchangeable in general — tabulation only works when every state depends '
                'on states that come strictly before it in your chosen order.'
            ),
            quote(
                'Reach for memoisation when the recursion is the clearest statement of the '
                'recurrence. Reach for tabulation when the depth is the thing that worries you.',
                caption='A workable rule',
            ),
            heading('The trap: caching states you never need'),
            para(
                'Top-down memoisation computes only the states reachable from the answer, '
                'which is a genuine advantage when the state space is large but mostly '
                'unreachable — knapsack with a small capacity is the classic example. Its '
                'cost is recursion overhead on every state and a cache you must keep alive.'
            ),
            bullets(
                '<b>Top-down</b> — computes a subset of states, higher constant factor, stack depth grows with n.',
                '<b>Bottom-up</b> — computes exactly the table you allocate, predictable cost, stack depth constant.',
                '<b>Neither</b> — if you can prove a greedy choice is always safe, that is <code>O(n)</code> and shorter.',
            ),
            DIVIDER,
            heading('Identifying the state'),
            para(
                'The practical work is deciding what a state is. A state must capture '
                'everything that changes the answer and nothing that does not. For a '
                'knapsack, the index alone is wrong — capacity matters too, which is why the '
                'naive <code>O(n·w)</code> table is the correct one.'
            ),
            link('https://en.wikipedia.org/wiki/Dynamic_programming', 'Dynamic programming on Wikipedia'),
        ),
    },
    {
        'slug': 'linked-lists-in-practice',
        'title': 'Linked Lists in Practice',
        'excerpt': (
            'The textbook linked list is rarely what you need. A singly linked list with a '
            'dummy head covers most of the cases people actually write by hand.'
        ),
        'category': 'dsa',
        'tags': ['linked-list', 'array'],
        'is_featured': False,
        'is_published': True,
        'content': document(
            heading('Why the textbook version frustrates people'),
            para(
                'Almost every linked-list question is phrased as "remove the nth node from the '
                'end" or "delete a node", and almost every solution starts with a special case '
                'for <i>what if it is the head</i>. That case exists only because the list has '
                'no sentinel.'
            ),
            para(
                'A <b>dummy head</b> — a node allocated up front whose <code>next</code> points '
                'at the first real element — removes the special case. The caller always gets '
                'a node back, and there is no branch anywhere in the body.'
            ),
            code('python', '''class ListNode:
    def __init__(self, value=0, next=None):
        self.value = value
        self.next = next


def remove_nth_from_end(head, n):
    dummy = ListNode(next=head)
    fast = slow = dummy

    for _ in range(n):
        fast = fast.next

    while fast.next:
        fast = fast.next
        slow = slow.next

    slow.next = slow.next.next
    return dummy.next'''),
            para(
                'The gap between <code>fast</code> and <code>slow</code> is the trick: advance '
                '<code>fast</code> by <code>n + 1</code> nodes and <code>slow</code> ends up on '
                'the node before the one to delete. No head check, no index arithmetic.'
            ),
            heading('The cost that makes people avoid them'),
            para(
                'Pointer chasing is the real difference, not asymptotics. An array index is one '
                'memory access; <code>node.next.value</code> is three, and the middle one may be '
                'a cache miss. In a list built by interleaving allocation with other objects, '
                'each hop can cost a hundred nanoseconds instead of one.'
            ),
            quote(
                'Use a linked list when you need O(1) splice at a position you already hold. '
                'Otherwise, the array is almost always faster and simpler.',
                caption='When it is actually the right structure',
            ),
            heading('Where they genuinely win'),
            bullets(
                'Free-threaded queues where <code>popleft</code> must not be <code>O(n)</code>.',
                'Intrusive structures, where the link lives inside your own object.',
                'LRU caches, where the recency list and the map must stay in lockstep.',
            ),
            heading('Reversing in place'),
            para(
                'Reversal is the one problem linked lists genuinely suit, because the operation '
                'is local: each node only needs to know its new predecessor.'
            ),
            code('python', '''def reverse(head):
    previous = None
    current = head

    while current:
        nxt = current.next
        current.next = previous
        previous = current
        current = nxt

    return previous'''),
            para(
                'Four local variables, no allocation, one pass. Written as '
                '<code>previous, current = current, previous</code> it stops working, which is '
                'why the unpacked form above is spelled out — the sequence of assignments is '
                'the algorithm.'
            ),
            DIVIDER,
            heading('Detecting a cycle'),
            para(
                'Floyd’s algorithm runs one pointer at speed and one at half speed. If they '
                'ever meet inside the list, there is a cycle. It uses <code>O(1)</code> space, '
                'unlike a visited set.'
            ),
            link('https://en.wikipedia.org/wiki/Floyd%27s_cycle-finding_algorithm', 'Floyd’s cycle-finding algorithm'),
        ),
    },
    {
        'slug': 'database-b-trees',
        'title': 'Inside a B-Tree',
        'excerpt': (
            'B-trees are why a database can answer a range query in a handful of page reads. '
            'The whole design is about one thing: not touching the disk.'
        ),
        'category': 'core-cs',
        'tags': ['tree'],
        'is_featured': False,
        'is_published': True,
        'content': document(
            heading('The constraint that shapes everything'),
            para(
                'Storage is not slow, it is <i>latency-bound</i>. An in-memory pointer '
                'dereference takes nanoseconds; a random read from an SSD takes tens of '
                'microseconds, and from a spinning disk, milliseconds. Three to four orders '
                'of magnitude. So the goal of an on-disk index is to minimise the number of '
                'reads per query, not to minimise comparisons.'
            ),
            para(
                'A B-tree of order <code>m</code> holds up to <code>m - 1</code> keys per node. '
                'Every node except the root is at least half full, which is what guarantees the '
                'height stays at <code>O(log m n)</code> and, in practice, three or four levels '
                'for a table that fits on a laptop.'
            ),
            heading('Why not a binary search tree'),
            bullets(
                'A balanced BST puts one key per node, so a million rows is a million nodes and '
                'twenty levels of pointer chasing.',
                'Disk pages hold hundreds of keys. One node per page wastes almost all of them.',
                'A B-tree node is sorted in memory, so a whole page of keys can be scanned with '
                'one binary search instead of twenty page reads.',
            ),
            heading('Why not B+ trees'),
            para(
                'In a B-tree, every key sits in an interior node pointing down. In a B+ tree — '
                'what almost every SQL database actually uses — interior nodes hold only '
                'separator keys, and all payloads live in the leaves, which are chained '
                'together.'
            ),
            para(
                'Two consequences fall out of that one change: interior nodes are small enough '
                'to keep cached, and a range query is a single descent plus a walk along one '
                'leaf chain. A <code>BETWEEN</code> clause touches maybe two interior nodes and '
                'three leaves regardless of how many rows it matches.'
            ),
            quote(
                'A B+ tree is a B-tree that decided the interior nodes should not hold data, '
                'so it could keep them in memory.',
                caption='The entire difference',
            ),
            heading('Splits, merges, and why the 50% floor exists'),
            para(
                'Inserting into a full node means splitting it and pushing a separator key up. '
                'Splitting a leaf is straightforward; splitting an interior node has to '
                'recompute which separator belonged where, which is why some implementations '
                'avoid splitting interior nodes and take the overflow to the parent instead.'
            ),
            para(
                'Deletions merge underfull nodes with their siblings. The 50% floor is what '
                'bounds the tree height; relax it and a sequence of deletes on one side can '
                'leave the tree thin enough to degenerate.'
            ),
            code('sql', '''-- This query is two B+ tree descents: one for 'k', one for 'z'.
SELECT title, created_at
FROM articles
WHERE slug BETWEEN 'k' AND 'z'
ORDER BY slug;'''),
            DIVIDER,
            heading('What this means when you write SQL'),
            para(
                'An index is a B+ tree keyed by the indexed columns, followed by a pointer to '
                'the row. Two practical consequences follow directly from the structure.'
            ),
            steps(
                'The leftmost column of a composite index determines the tree order, so '
                '<code>WHERE b = ?</code> cannot use an index on <code>(a, b)</code>.',
                'The index stores the indexed columns then the row pointer, so a covering query '
                'never touches the table at all.',
                'Because keys in a node are sorted, a range predicate stops being usable for '
                'rows past the range — the tree can only seek, not filter.',
            ),
            para(
                'That third point is why <code>WHERE created_at &gt; now() - interval \'7 days\'</code> '
                'uses the index while <code>WHERE extract(year from created_at) = 2026</code> '
                'does not: a function on the column destroys the ordering the tree depends on.',
            ),
            link('https://en.wikipedia.org/wiki/B%2B_tree', 'B+ tree'),
        ),
    },
    {
        'slug': 'load-balancing-strategies',
        'title': 'Choosing a Load Balancing Strategy',
        'excerpt': (
            'Round robin is the default and the wrong answer surprisingly often. What to pick '
            'instead depends entirely on whether your backends hold state.'
        ),
        'category': 'system-design',
        'tags': ['graph'],
        'is_featured': False,
        'is_published': False,
        'content': document(
            heading('Start from the constraint, not the algorithm'),
            para(
                'Load balancing strategies are usually compared on how fairly they distribute '
                'requests. That is the least interesting property. The question that decides '
                'your choice is whether a request can be served by <b>any</b> backend or only '
                'by the one that holds the relevant state.'
            ),
            heading('Stateless backends'),
            para(
                'If every backend can serve any request, the distribution method matters only '
                'to the extent that request cost varies. If it does, weighted round robin '
                'beats anything smarter.'
            ),
            bullets(
                '<b>Round robin</b> — cheapest, and correct when requests cost the same.',
                '<b>Weighted round robin</b> — the right answer the moment one backend type is '
                'bigger, or an endpoint is heavier.',
                '<b>Least connections</b> — useful for long-lived connections where request '
                'count is a poor proxy for load.',
                '<b>Least response time</b> — adapts without configuration, but needs enough '
                'traffic per backend to be statistically meaningful.',
            ),
            heading('Stateful backends'),
            para(
                'Once sessions, caches or websockets pin a client to a backend, you have moved '
                'the problem rather than solved it. Two honest options exist.'
            ),
            steps(
                '<b>Make it stateless.</b> Move the session to shared storage, or embed a signed '
                'session cookie in the response. Then any strategy works.',
                '<b>Route consistently.</b> Hash on a client identifier so the same client '
                'always reaches the same backend.',
            ),
            para(
                'Consistent hashing is the answer to the second option’s obvious objection: '
                'adding a backend remaps most keys, whereas consistent hashing only remaps '
                '<code>1 / n</code> of them. Load balancers such as <code>envoy</code> expose it '
                'as a ring hash.'
            ),
            quote(
                'Every session-affinity scheme is a caching layer with a very short timeout. '
                'Treat it that way.',
                caption='How to think about sticky sessions',
            ),
            heading('Health checking is not optional'),
            para(
                'A strategy is only as good as its view of which backends are alive. Passive '
                'checks count failures, which means a hung — not crashed — backend keeps '
                'receiving traffic until it trips the threshold. Active checks ask, which is '
                'slower to detect but does not require traffic to fail first.'
            ),
            bullets(
                'Active probing for backends that can hang, such as anything with a database connection pool.',
                'Passive failure counting for stateless workers, where a failed request is cheap and informative.',
                'Never remove a backend without draining it, or in-flight requests return 502 during every deploy.',
            ),
            DIVIDER,
            heading('Where this is decided in practice'),
            para(
                'At the edge, a CDN balances by cache hit — the request never reaches you at all. '
                'Behind it, the ingress controller balances by the strategy above. In between, '
                'the service mesh balances per connection. Each layer has its own default, and '
                'the defaults rarely agree.'
            ),
            link('https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancing', 'Envoy: load balancing'),
        ),
    },
    {
        'slug': 'big-o-without-hand-waving',
        'title': 'Big-O Without the Hand-Waving',
        'excerpt': (
            'A practical guide to reading growth rates, dropping constants, and '
            'knowing which complexity claim is actually being made.'
        ),
        'category': 'core-cs',
        'tags': ['array', 'dp'],
        'is_featured': True,
        'is_published': True,
        'content': document(
            heading('What Big-O actually claims'),
            para(
                'Big-O describes how the work grows as the input grows. It deliberately '
                'ignores constants, hardware, and small inputs. That makes it useful for '
                'comparing algorithms and useless for predicting whether a particular '
                'function takes 2 ms or 20 ms.'
            ),
            heading('The three rules'),
            steps(
                'Drop constant factors: <code>3n</code> and <code>n</code> are both '
                '<code>O(n)</code>.',
                'Keep the fastest-growing term: <code>n^2 + n</code> is <code>O(n^2)</code> '
                'for large <code>n</code>.',
                'Nested loops multiply; sequential loops add. Two separate <code>n</code> '
                'passes are still <code>O(n)</code>.',
            ),
            heading('The common classes'),
            bullets(
                '<code>O(1)</code> — a hash lookup or array index.',
                '<code>O(log n)</code> — binary search; the range halves each step.',
                '<code>O(n)</code> — one pass over the input.',
                '<code>O(n log n)</code> — comparison sorting, or a linear pass inside a '
                'divide-and-conquer recursion.',
                '<code>O(n^2)</code> — a nested pass over the same collection.',
                '<code>O(2^n)</code> — exploring every subset; fine only for tiny inputs.',
            ),
            heading('A worked example'),
            para(
                'This function looks like it does two things, but the second loop runs '
                'over the input again. The total is <code>O(n)</code>, not '
                '<code>O(n^2)</code>.'
            ),
            code('python', '''def summarise(items):
    total = 0
    for item in items:       # n steps
        total += item

    positives = 0
    for item in items:       # another n steps
        if item > 0:
            positives += 1

    return total, positives'''),
            heading('Worst case, average case, amortised'),
            para(
                'Big-O on its own does not say which case it is describing. A hash map '
                'lookup is <code>O(1)</code> on average and <code>O(n)</code> in the '
                'worst case when every key collides. A dynamic array append is '
                '<code>O(1)</code> amortised because the occasional resize is paid for '
                'by the many cheap appends before it.'
            ),
            quote(
                'Big-O is a shape, not a stopwatch. Say which case you mean, or the '
                'claim is incomplete.',
                caption='The habit worth building',
            ),
            heading('What Big-O hides'),
            para(
                'Constants matter at real input sizes. An <code>O(n log n)</code> sort '
                'with a large constant can lose to an <code>O(n^2)</code> insertion sort '
                'on a hundred elements. Cache locality, allocation, and branch '
                'prediction are invisible to the notation but very visible in a profiler.'
            ),
            DIVIDER,
            heading('How to answer in an interview'),
            steps(
                'Name the input that the complexity is measured against.',
                'Count the loops and the work inside them, not the lines of code.',
                'Separate the data structure costs from the algorithm costs.',
                'State the case: best, average, worst, or amortised.',
            ),
        ),
    },
    {
        'slug': 'http-caching-in-practice',
        'title': 'HTTP Caching in Practice',
        'excerpt': (
            'Freshness, validation, and the headers that decide whether a request '
            'ever reaches your server.'
        ),
        'category': 'web-dev',
        'tags': [],
        'is_featured': False,
        'is_published': True,
        'content': document(
            heading('Two different questions'),
            para(
                'A cache asks two things: may I reuse this response without asking the '
                'server, and if I must ask, can the server tell me nothing changed? The '
                'first is freshness; the second is validation.'
            ),
            heading('Freshness: max-age'),
            para(
                '<code>Cache-Control: max-age=60</code> says the response is fresh for '
                'sixty seconds. While it is fresh, the browser may reuse it without a '
                'network request. After that it becomes stale, but stale does not mean '
                'unusable.'
            ),
            code('http', '''Cache-Control: public, max-age=60, stale-while-revalidate=30'''),
            heading('Validation: ETag and If-None-Match'),
            para(
                'An <code>ETag</code> is a fingerprint of the representation. On the next '
                'request the browser sends it back as <code>If-None-Match</code>. If the '
                'resource still has the same fingerprint, the server answers '
                '<code>304 Not Modified</code> with no body.'
            ),
            steps(
                'The browser caches the response and its <code>ETag</code>.',
                'The response becomes stale.',
                'The browser sends <code>If-None-Match: "abc123"</code>.',
                'The server compares the tag and returns <code>304</code> or a fresh '
                '<code>200</code>.',
            ),
            heading('public, private, and no-store'),
            bullets(
                '<code>public</code> — any shared cache, including a CDN, may store it.',
                '<code>private</code> — only the browser may store it; a CDN must not.',
                '<code>no-store</code> — do not write it to disk at all. Use it for '
                'secrets and personalised data.',
                '<code>no-cache</code> — store it, but validate before every reuse. This '
                'is not the same as <code>no-store</code>.',
            ),
            heading('The mistakes that bite'),
            bullets(
                'Caching an authenticated response as <code>public</code>, then serving '
                'it to another user.',
                'Forgetting <code>Vary: Accept-Encoding</code> when the response differs '
                'by compression.',
                'Setting a long <code>max-age</code> on HTML that points at hashed '
                'assets, instead of caching the hashed assets forever and the HTML '
                'briefly.',
                'Treating <code>no-cache</code> as "do not cache"; it means "revalidate '
                'first".',
            ),
            quote(
                'Cache the immutable thing for a year. Cache the pointer to it for a '
                'minute.',
                caption='The asset strategy in one line',
            ),
            heading('A cache is a contract'),
            para(
                'Every cache header is a promise about who may store the response and '
                'for how long. A wrong promise is not a performance bug; it is a '
                'correctness bug that shows up as one user seeing another user’s data.'
            ),
        ),
    },
    {
        'slug': 'cap-theorem-in-practice',
        'title': 'The CAP Theorem in Practice',
        'excerpt': (
            'What consistency, availability, and partition tolerance actually force '
            'you to choose when the network fails.'
        ),
        'category': 'system-design',
        'tags': ['graph'],
        'is_featured': False,
        'is_published': True,
        'content': document(
            heading('The theorem, stated honestly'),
            para(
                'CAP says that when a network partition occurs, a distributed system '
                'must choose between consistency and availability. It does not say you '
                'pick two of three all the time; partitions are rare, and the choice '
                'only becomes visible while one is happening.'
            ),
            heading('What the letters mean'),
            bullets(
                '<b>Consistency</b> — every read sees the most recent write. This is '
                'stronger than the C in ACID.',
                '<b>Availability</b> — every request to a non-failing node gets a '
                'non-error response, without a guarantee that it is the latest write.',
                '<b>Partition tolerance</b> — the system keeps operating when messages '
                'between nodes are lost or delayed.',
            ),
            heading('CP versus AP'),
            para(
                'A CP system refuses reads or writes it cannot prove are current. A '
                'banking ledger usually prefers this: an error is better than a wrong '
                'balance. An AP system keeps answering and reconciles later. A social '
                'feed usually prefers this: a slightly stale post is better than a '
                'failed page load.'
            ),
            code('text', '''Partition occurs:
  CP -> reject the request, preserve a single truth
  AP -> answer from the local replica, converge afterwards'''),
            heading('The part people forget'),
            para(
                'Partition tolerance is not optional. You can choose to give up '
                'consistency or availability during a partition, but you cannot choose '
                'to make the network reliable. The real design question is what the '
                'system does while the partition lasts.'
            ),
            heading('Beyond CAP: latency'),
            para(
                'PACELC extends the idea: if there is a partition, choose availability '
                'or consistency; else, choose latency or consistency. Even with a '
                'healthy network, a strongly consistent read may have to wait for a '
                'quorum, and that wait is a product decision.'
            ),
            quote(
                'CAP is a question about the worst minute, not the normal day.',
                caption='Why the theorem is easy to misquote',
            ),
            heading('A practical checklist'),
            steps(
                'Name the operation that must never return stale data.',
                'Decide what a request should do when that operation cannot reach a '
                'quorum.',
                'Write down how the system reconciles after the partition heals.',
                'Measure the latency cost of the consistency you chose.',
            ),
        ),
    },
]


# Questions for the "Quiz me" button. Keyed by article slug so the seed can
# skip an article that does not exist (or was renamed) rather than failing the
# whole command. Each entry is four options plus the zero-based correct one.
# `get_or_create` is keyed on the prompt, so re-seeding never overwrites a
# question an editor has since rewritten.
QUIZ_QUESTIONS = {
    'two-sum-explained': [
        {
            'prompt': 'Which data structure does the walkthrough use to find the complement?',
            'options': ['A hash map', 'A sorted array', 'A linked list', 'A stack'],
            'correct': 0,
            'explanation': (
                'The solution stores each value it has seen in a hash map, so the '
                'complement of the current number can be looked up in constant time.'
            ),
        },
        {
            'prompt': 'What does the hash map hold for each number that has been seen?',
            'options': ['Its index', 'Its complement', 'Its frequency', 'Its square'],
            'correct': 0,
            'explanation': (
                'The map is keyed by the number and stores its index, because the '
                'answer is a pair of indices rather than the values themselves.'
            ),
        },
        {
            'prompt': 'What is the time complexity of the one-pass hash map solution?',
            'options': ['O(n)', 'O(log n)', 'O(n log n)', 'O(n^2)'],
            'correct': 0,
            'explanation': (
                'Each element is visited once and each hash map lookup is O(1) on '
                'average, so the whole pass is O(n).'
            ),
        },
        {
            'prompt': 'Why does the solution check the map before inserting the current number?',
            'options': [
                'It prevents a number from matching itself',
                'It keeps the map sorted',
                'It avoids duplicate indices in the output',
                'It reduces the space complexity',
            ],
            'correct': 0,
            'explanation': (
                'Checking first means the current number cannot be paired with '
                'itself; the match must come from an earlier index.'
            ),
        },
        {
            'prompt': 'What is the space complexity of the solution?',
            'options': ['O(n)', 'O(1)', 'O(log n)', 'O(n^2)'],
            'correct': 0,
            'explanation': (
                'In the worst case the map holds every number before the pair is '
                'found, which grows linearly with the input.'
            ),
        },
    ],
    'binary-search-boundaries': [
        {
            'prompt': 'What must be true of the input before binary search can be used?',
            'options': [
                'It must be sorted',
                'It must contain no duplicates',
                'It must have an even length',
                'It must fit in memory',
            ],
            'correct': 0,
            'explanation': (
                'The algorithm discards half the range based on one comparison, '
                'which is only valid when the data is ordered.'
            ),
        },
        {
            'prompt': 'What is the time complexity of binary search?',
            'options': ['O(log n)', 'O(n)', 'O(n log n)', 'O(1)'],
            'correct': 0,
            'explanation': (
                'Each comparison halves the candidate range, so the number of '
                'steps grows with the logarithm of the input size.'
            ),
        },
        {
            'prompt': 'In the half-open formulation, when is the range [lo, hi) empty?',
            'options': ['When lo == hi', 'When lo > hi', 'When lo == 0', 'When hi == n'],
            'correct': 0,
            'explanation': (
                'A half-open range includes lo but excludes hi, so it contains '
                'nothing exactly when the two bounds meet.'
            ),
        },
        {
            'prompt': 'Why does the article use lo = mid + 1 after a low comparison?',
            'options': [
                'mid is known not to be the target, so it can be discarded',
                'It keeps mid in the range for the next step',
                'It avoids an infinite loop in Python only',
                'It makes the midpoint calculation simpler',
            ],
            'correct': 0,
            'explanation': (
                'If the value at mid is too small, mid itself cannot be the '
                'answer; leaving it in the range can shrink the low side by only '
                'one element at a time.'
            ),
        },
        {
            'prompt': 'Which midpoint expression stays safe in a language with fixed-width integers?',
            'options': [
                'lo + (hi - lo) // 2',
                '(lo + hi) // 2',
                'hi - (lo + hi) // 2',
                '(lo * hi) // 2',
            ],
            'correct': 0,
            'explanation': (
                'Subtracting first keeps the sum from overflowing. The two forms '
                'agree in Python, where integers have arbitrary precision, but not '
                'in every language.'
            ),
        },
    ],
    'big-o-without-hand-waving': [
        {
            'prompt': 'What does Big-O primarily describe?',
            'options': [
                'The exact running time in milliseconds',
                'The number of lines in a function',
                'How work grows as the input size grows',
                'Peak memory use only',
            ],
            'correct': 2,
            'explanation': (
                'Big-O is a growth-rate notation. It compares how the work scales, '
                'not how long a particular machine takes.'
            ),
        },
        {
            'prompt': 'Simplify 3n + 5.',
            'options': ['O(3n)', 'O(n)', 'O(5)', 'O(n^2)'],
            'correct': 1,
            'explanation': (
                'Constant factors and lower-order terms are dropped, leaving O(n).'
            ),
        },
        {
            'prompt': 'Simplify n^2 + n.',
            'options': ['O(n)', 'O(n^2 + n)', 'O(n^2)', 'O(2n)'],
            'correct': 2,
            'explanation': (
                'For large n the n^2 term dominates, so the lower-order n term is '
                'dropped.'
            ),
        },
        {
            'prompt': 'Two separate loops, each over all n items, are…',
            'options': ['O(n)', 'O(n^2)', 'O(log n)', 'O(2^n)'],
            'correct': 0,
            'explanation': (
                'Sequential loops add: n + n is still linear, so the result is O(n).'
            ),
        },
        {
            'prompt': 'A loop over n items containing another loop over n items is…',
            'options': ['O(n)', 'O(log n)', 'O(n log n)', 'O(n^2)'],
            'correct': 3,
            'explanation': (
                'Nested loops multiply: n work for the outer loop times n work for '
                'the inner loop gives O(n^2).'
            ),
        },
        {
            'prompt': 'Binary search on a sorted array is…',
            'options': ['O(1)', 'O(log n)', 'O(n)', 'O(n log n)'],
            'correct': 1,
            'explanation': (
                'Each comparison halves the candidate range, which produces a '
                'logarithmic number of steps.'
            ),
        },
        {
            'prompt': 'A comparison sort is typically…',
            'options': ['O(n)', 'O(log n)', 'O(n log n)', 'O(2^n)'],
            'correct': 2,
            'explanation': (
                'Comparison sorting has a well-known O(n log n) lower bound for the '
                'general case.'
            ),
        },
        {
            'prompt': 'A hash map lookup is, on average…',
            'options': ['O(1)', 'O(log n)', 'O(n)', 'O(n^2)'],
            'correct': 0,
            'explanation': (
                'With a good hash function the key maps directly to a bucket, so '
                'the expected lookup cost is constant.'
            ),
        },
        {
            'prompt': 'A hash map lookup with every key colliding is, in the worst case…',
            'options': ['O(1)', 'O(log n)', 'O(n/2)', 'O(n)'],
            'correct': 3,
            'explanation': (
                'If every key lands in the same bucket, the lookup may scan all n '
                'entries, which is O(n).'
            ),
        },
        {
            'prompt': 'Appending to a dynamic array is…',
            'options': [
                'O(n) every time',
                'O(1) amortised',
                'O(log n) amortised',
                'O(n log n) amortised',
            ],
            'correct': 1,
            'explanation': (
                'A resize copies the array, but the many cheap appends between '
                'resizes pay for it, so the amortised cost is constant.'
            ),
        },
        {
            'prompt': 'Which statement about Big-O is false?',
            'options': [
                'It ignores constant factors',
                'It describes growth rather than exact time',
                'It can hide cache and allocation costs',
                'It predicts exact milliseconds on real hardware',
            ],
            'correct': 3,
            'explanation': (
                'Big-O says nothing about exact wall-clock time; constants, cache '
                'behaviour, and hardware all matter in practice.'
            ),
        },
        {
            'prompt': (
                'Why can an O(n^2) insertion sort beat an O(n log n) sort on a '
                'small array?'
            ),
            'options': [
                'Its constant factors and overhead are smaller',
                'Big-O is mathematically wrong',
                'Insertion sort is asymptotically faster',
                'It uses no comparisons',
            ],
            'correct': 0,
            'explanation': (
                'Asymptotic notation describes large inputs. On small inputs the '
                'lower overhead of insertion sort can win despite its worse growth.'
            ),
        },
    ],
    'http-caching-in-practice': [
        {
            'prompt': 'What does Cache-Control: max-age=60 mean?',
            'options': [
                'The response must be revalidated every 60 seconds',
                'The response is fresh for 60 seconds',
                'The response expires after 60 requests',
                'The cache must delete it after 60 seconds',
            ],
            'correct': 1,
            'explanation': (
                'max-age sets a freshness lifetime. While the response is fresh, a '
                'cache may reuse it without contacting the server.'
            ),
        },
        {
            'prompt': 'What does a 304 Not Modified response tell the browser?',
            'options': [
                'The resource was deleted',
                'The server is unavailable',
                'The cached copy is still valid and should be reused',
                'The response body follows in a second request',
            ],
            'correct': 2,
            'explanation': (
                'A 304 is the server confirming that the cached representation is '
                'still current, so no new body is sent.'
            ),
        },
        {
            'prompt': 'What is the difference between no-store and no-cache?',
            'options': [
                'no-store never writes the response; no-cache stores it but revalidates before reuse',
                'no-cache never writes; no-store revalidates',
                'They are identical',
                'no-store only applies to CDNs',
            ],
            'correct': 0,
            'explanation': (
                'no-store forbids writing the response at all, while no-cache allows '
                'storage but requires validation before every reuse.'
            ),
        },
        {
            'prompt': 'Which Cache-Control value allows a shared CDN to store the response?',
            'options': ['private', 'public', 'no-store', 'Set-Cookie'],
            'correct': 1,
            'explanation': (
                'public explicitly permits shared caches, including CDNs, to store '
                'the response.'
            ),
        },
        {
            'prompt': 'What does an ETag identify?',
            'options': [
                'The server’s IP address',
                'The user’s session',
                'A fingerprint of the representation',
                'The cache’s expiry time',
            ],
            'correct': 2,
            'explanation': (
                'An ETag is an opaque validator for the selected representation. '
                'If it still matches, the cached copy is still valid.'
            ),
        },
        {
            'prompt': 'Which is a correctness bug rather than a performance bug?',
            'options': [
                'Caching an authenticated response as public and serving it to another user',
                'Caching a hashed asset for a year',
                'Using a short max-age for HTML',
                'Sending Vary: Accept-Encoding',
            ],
            'correct': 0,
            'explanation': (
                'A shared cache must never serve one user’s private response to '
                'another. That is a data leak, not a speed problem.'
            ),
        },
    ],
    'cap-theorem-in-practice': [
        {
            'prompt': 'According to CAP, what must a system choose during a network partition?',
            'options': [
                'Consistency or availability',
                'Latency or throughput',
                'SQL or NoSQL',
                'Encryption or compression',
            ],
            'correct': 0,
            'explanation': (
                'CAP is specifically about the trade-off between consistency and '
                'availability while the network is partitioned.'
            ),
        },
        {
            'prompt': 'A CP system usually sacrifices which property during a partition?',
            'options': ['Partition tolerance', 'Availability', 'Durability', 'Latency'],
            'correct': 1,
            'explanation': (
                'A CP system preserves consistency by refusing requests it cannot '
                'prove are current, which means giving up availability.'
            ),
        },
        {
            'prompt': 'An AP system usually sacrifices which property during a partition?',
            'options': [
                'Immediate consistency',
                'Partition tolerance',
                'Durability',
                'Availability',
            ],
            'correct': 0,
            'explanation': (
                'An AP system keeps answering from local replicas, so different '
                'nodes may temporarily return different values.'
            ),
        },
        {
            'prompt': 'Why is partition tolerance not optional?',
            'options': [
                'Because databases require it',
                'Because it is the same as consistency',
                'Because every system must use replication',
                'Because networks can lose or delay messages',
            ],
            'correct': 3,
            'explanation': (
                'You cannot make the network reliable. The design question is what '
                'the system does when a partition happens.'
            ),
        },
        {
            'prompt': 'What does PACELC add to CAP?',
            'options': [
                'A latency-versus-consistency choice when there is no partition',
                'A third consistency model',
                'A rule that partitions never happen',
                'A requirement to use quorums',
            ],
            'correct': 0,
            'explanation': (
                'PACELC extends CAP with the normal-case trade-off between latency '
                'and consistency when the network is healthy.'
            ),
        },
    ],
}


class Command(BaseCommand):
    help = 'Seed database with sample data'

    def handle(self, *args, **options):
        self.stdout.write('Seeding categories...')
        cats = {}
        for name, slug in [
            ('DSA', 'dsa'),
            ('System Design', 'system-design'),
            ('Web Dev', 'web-dev'),
            ('Core CS', 'core-cs'),
        ]:
            c, _ = Category.objects.get_or_create(name=name, slug=slug)
            cats[slug] = c

        self.stdout.write('Seeding tags...')
        tags = {}
        # Each tag is filed under exactly one category. The mapping keeps the
        # sample taxonomy browsable and matches the backfill the
        # `tag.category` migration performs for pre-existing rows.
        for name, category_slug in [
            ('array', 'dsa'),
            ('linked-list', 'dsa'),
            ('tree', 'core-cs'),
            ('dp', 'dsa'),
            ('graph', 'system-design'),
            ('recursion', 'dsa'),
        ]:
            t, _ = Tag.objects.get_or_create(
                name=name,
                defaults={'slug': name, 'category': cats[category_slug]},
            )
            # Backfill a category for tags seeded before the relation existed.
            if t.category_id is None:
                t.category = cats[category_slug]
                t.save(update_fields=['category'])
            tags[name] = t

        # Every article below needs an author or it renders with no byline at
        # all, so a placeholder byline is created before any content is written.
        author = self.get_site_author()

        self.stdout.write('Seeding articles...')
        self.seed_walkthrough(cats, tags, author)
        for spec in ARTICLES:
            self.seed_article(spec, cats, tags, author)

        self.stdout.write('Seeding quiz questions...')
        self.seed_quizzes()

        self.stdout.write(self.style.SUCCESS('Seed complete.'))

    def get_site_author(self):
        """Return the user that sample content is attributed to.

        Article.author is nullable, so seeding without one silently produces a
        site whose every article shows no byline. Real signups arrive through
        Supabase, so the seed cannot rely on an existing account: it falls back
        to a dedicated placeholder rather than borrowing whichever staff user
        happens to exist first.
        """
        User = get_user_model()
        author, created = User.objects.get_or_create(
            username='csehub',
            defaults={
                'email': 'author@csehub.local',
                'display_name': 'CSEHub',
                'is_staff': True,
                'is_active': True,
            },
        )
        if created:
            author.set_unusable_password()
            author.save(update_fields=['password'])
            self.stdout.write('Created placeholder author "CSEHub".')
        return author

    def seed_article(self, spec, cats, tags, author):
        # get_or_create on slug only: re-running never overwrites an author's edits.
        article, created = Article.objects.get_or_create(
            slug=spec['slug'],
            defaults={
                'title': spec['title'],
                'excerpt': spec['excerpt'],
                'content': spec['content'],
                'category': cats[spec['category']],
                'author': author,
                'is_published': spec['is_published'],
                'is_featured': spec['is_featured'],
            },
        )
        if not created:
            # Backfill rows seeded before `author` was populated. Restricted to
            # the NULL case so a byline assigned later through the admin panel
            # survives a re-seed.
            if article.author_id is None:
                article.author = author
                article.save(update_fields=['author'])
            return article

        for tag_slug in spec['tags']:
            ArticleTag.objects.get_or_create(article=article, tag=tags[tag_slug])
        return article

    def seed_quizzes(self):
        """Attach the sample questions to articles that exist.

        Idempotent per (article, prompt): a re-seed adds missing questions but
        never overwrites one an editor has since rewritten. An article that was
        never seeded, or was renamed, is skipped rather than failing the whole
        command.
        """
        for slug, specs in QUIZ_QUESTIONS.items():
            article = Article.objects.filter(slug=slug).first()
            if article is None:
                continue
            for spec in specs:
                options = spec['options']
                QuizQuestion.objects.get_or_create(
                    article=article,
                    prompt=spec['prompt'],
                    defaults={
                        'option_a': options[0],
                        'option_b': options[1],
                        'option_c': options[2],
                        'option_d': options[3],
                        'correct_option': spec['correct'],
                        'explanation': spec.get('explanation', ''),
                    },
                )

    def seed_walkthrough(self, cats, tags, author):
        article, created = Article.objects.get_or_create(
            slug='two-sum-explained',
            defaults={
                'title': 'Two Sum — Explained',
                'content': document(
                    heading('Problem'),
                    para(
                        'Given an array of integers <code>nums</code> and an integer target, '
                        'return the indices of the two numbers that add up to target.'
                    ),
                    heading('Approach'),
                    para('Use a hashmap to store complement values as you iterate.'),
                    heading('Complexity'),
                    para('Time: O(n) | Space: O(n)'),
                ),
                'excerpt': 'A hashmap-based walkthrough of the classic Two Sum problem.',
                'category': cats['dsa'],
                'author': author,
                'is_published': True,
            }
        )
        if not created:
            if article.author_id is None:
                article.author = author
                article.save(update_fields=['author'])
            return
        if created:
            ArticleTag.objects.get_or_create(article=article, tag=tags['array'])
            ArticleTag.objects.get_or_create(article=article, tag=tags['dp'])
            CodeSnippet.objects.get_or_create(
                article=article,
                order=1,
                defaults={
                    'language': 'python',
                    'code': (
                        'def twoSum(nums, target):\n'
                        '    seen = {}\n'
                        '    for i, num in enumerate(nums):\n'
                        '        complement = target - num\n'
                        '        if complement in seen:\n'
                        '            return [seen[complement], i]\n'
                        '        seen[num] = i'
                    ),
                }
            )
