import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { Landing, greetingFor } from './landing';

describe('greetingFor', () => {
  const at = (hour: number, minute = 0) => greetingFor(new Date(2026, 9, 6, hour, minute));

  it('greets by the time of day', () => {
    expect(at(5)).toBe('Good morning');
    expect(at(11, 59)).toBe('Good morning');
    expect(at(12)).toBe('Good afternoon');
    expect(at(16, 59)).toBe('Good afternoon');
    expect(at(17)).toBe('Good evening');
    expect(at(23)).toBe('Good evening');
    expect(at(2)).toBe('Good evening'); // the small hours still feel like evening
  });
});

describe('Landing demo stories card', () => {
  async function render() {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const fixture = TestBed.createComponent(Landing);
    fixture.detectChanges();
    TestBed.inject(HttpTestingController)
      .expectOne('/api/simulator/stories')
      .flush({
        demo: [
          { story_id: 'st_1', title: 'SYNTHETIC first', region: 'Behind the scenes', tones: [] },
          { story_id: 'st_2', title: 'SYNTHETIC second', region: 'Behind the scenes', tones: [] },
        ],
        news_count: 4,
      });
    fixture.detectChanges();
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('shows the demo stories and the count of today\'s news', async () => {
    const element = await render();
    const titles = [...element.querySelectorAll('.tile h3')].map((h) => h.textContent);
    expect(titles).toEqual(['SYNTHETIC first', 'SYNTHETIC second', "Today's stories"]);
    expect(element.querySelector('.stat-value')?.textContent).toBe('4');
  });

  it('tells a tapped story by its id, and opens the listening screen', async () => {
    const element = await render();
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    element.querySelectorAll<HTMLButtonElement>('.tile')[1].click();

    // The listening screen owns the conversation: the story goes along as its opening.
    expect(navigate).toHaveBeenCalledWith(['/listen'], {
      state: { opening: { text: 'Tell me SYNTHETIC second', storyId: 'st_2' } },
    });
  });
});
