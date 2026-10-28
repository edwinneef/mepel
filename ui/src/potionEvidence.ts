export interface PotionReading {
  frame: string; sequence: number; captured_at: number; capture_clock: number;
  percent: number; confidence: number;
}
export interface PotionRecord {
  id: string; session_id: string; recording: string; ticket: number; resource: 'hp' | 'mp';
  status: string; baseline_usable: boolean; before: PotionReading | null; after: PotionReading | null;
  outcome: { result: string; finished_at: number } | null;
}
export interface PotionEvidence { enabled: boolean; records: PotionRecord[] }
