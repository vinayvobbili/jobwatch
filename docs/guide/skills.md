# Skills to build

[← jobwatch guide](README.md)

Which skills do the jobs you're going after ask for that your resume doesn't show, and where can you learn
them in the time you have?

```
jobwatch skills                     # gaps across today's matches and your applications
jobwatch skills --timeline month    # week, month, quarter (default) or any
jobwatch skills --all               # also the skills your resume already shows
```

The Skills tab in `jobwatch ui` shows the same, with a timeline switch, and each job's details link to it
from the gaps it lists.

Skills are ranked by demand: how many of your matching jobs mention one, with a must-have that a fit score
found missing counting three times. Each comes with:
- curated courses and certifications from the official pages (AWS, Linux Foundation, DeepLearning.AI,
  Hugging Face, OWASP...), each with a rough time and marked if it's longer than your timeline;
- searches on LinkedIn Learning, Coursera, edX and, for AI skills, DeepLearning.AI;
- with a timeline of a quarter or more, certificate programs at colleges near you.

Fit-score gaps no course closes (a clearance, citizenship, a degree, travel) are listed apart, and so are
must-haves asking for years of something: a course gives you something concrete to point to, not the years.

```yaml
learning:
  timeline: quarter       # week, month, quarter or any
  near: Denver            # for colleges nearby; default: the first city in filters.locations
  jobs: 5                 # example jobs listed with each skill
```

The chat knows the top gaps too ("what should I learn this month?"), and a job's details list the skills
that posting asks for that your resume doesn't show.
