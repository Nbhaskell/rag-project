"""Makes demo_docs/07-visitor-guide.pdf, a made-up 3-page PDF for the fictional dog daycare.

The six daycare documents are markdown, which has headings but no pages. This PDF is there so the demo
has a real PDF whose answers can be traced to a page number. It is new content, so the saved eval numbers
for those six stay comparable: nothing in it repeats or contradicts the six documents, and it must not answer
any question the eval sets treat as unanswerable (an earlier version had a page about tours, which made the
held-out question `unknown-tour` answerable).

Needs the fpdf2 package, which is only for this script and is not in requirements.txt:

    pip install fpdf2
    python tools/make_demo_pdf.py

The creation date is fixed, so running it again gives the same file.
"""
import datetime
from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).resolve().parent.parent / "demo_docs" / "07-visitor-guide.pdf"

# Plain ASCII only: the standard PDF fonts used here have no curly quotes or long dashes.
PAGES = [
    ("Barks n Woofs: Visitor Guide", [
        ("Finding us",
         "Barks n Woofs is at 123 puppy drive, Oakland ME. Look for the green awning. The front door is for "
         "visitors. Dogs being dropped off or picked up use the side door."),
        ("Parking",
         "Free parking is in the lot behind the building. There are 12 spaces, including 2 close to the side door "
         "for drop-off. The lot is lit until 7:00pm. Please do not park in the delivery lane next to the "
         "dumpsters."),
        ("Arriving with your dog",
         "Keep your dog on a leash until you are inside the lobby. Please do not let your dog greet other dogs in "
         "the parking lot."),
    ]),
    ("Pick-up and Accessibility", [
        ("Waiting at pick-up",
         "At pick-up, wait at the lobby counter. Staff bring your dog out to you with the daily report. Please do "
         "not go into the play areas yourself, even if you can see your dog through the gate."),
        ("Greeting other dogs",
         "Keep your dog on a leash in the lobby. Please ask the other owner before you let your dog greet another "
         "dog, and give shy dogs plenty of room."),
        ("Accessibility",
         "The lobby, the side door and the restroom have no steps. A ramp leads up from the parking lot, and the "
         "lobby counter has a lowered section for wheelchair users."),
    ]),
    ("Lost and Found, Photos and Quiet Hours", [
        ("Lost and found",
         "Items left behind are kept at the front desk for 30 days. Collars, leashes and toys are washed before "
         "they are given back. After 30 days unclaimed items are given to a local rescue."),
        ("Photos",
         "Staff take photos for the daily report that goes to owners. We never post a dog's photo on social media "
         "without written permission from the owner."),
        ("Quiet hours",
         "During nap time, 12:00pm to 2:30pm, the play yards are closed to visitors so that dogs can rest. "
         "Please avoid dropping by during this time."),
    ]),
]


def build():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    pdf.set_title("Barks n Woofs: Visitor Guide")
    pdf.set_creation_date(datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc))
    for title, sections in PAGES:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(0, 14, title, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        for heading, text in sections:
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 8, heading, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=12)
            pdf.multi_cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)
    OUT.parent.mkdir(exist_ok=True)
    pdf.output(str(OUT))
    return OUT


if __name__ == "__main__":
    print(f"Wrote {build()}")
