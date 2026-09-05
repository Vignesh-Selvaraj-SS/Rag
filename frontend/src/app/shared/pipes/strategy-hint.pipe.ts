import { Pipe, PipeTransform } from '@angular/core';
import { ChunkStrategyInfo } from '../../core/models';

/** Description text for the selected chunking strategy. */
@Pipe({ name: 'strategyHint' })
export class StrategyHintPipe implements PipeTransform {
  transform(strategies: ChunkStrategyInfo[], id: string): string {
    return strategies.find((strategy) => strategy.id === id)?.description ?? '';
  }
}
