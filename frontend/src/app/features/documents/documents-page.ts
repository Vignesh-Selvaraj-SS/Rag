import { HttpEventType } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiError, ChunkStrategy, DocumentInfo, IndexStatus } from '../../core/models';
import { DocumentApiService } from '../../core/services/document-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { ServerConfigService } from '../../core/services/server-config.service';
import { ConfirmDialog } from '../../shared/components/confirm-dialog/confirm-dialog';
import { EmptyState } from '../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../shared/components/loading-indicator/loading-indicator';
import { PageHeader } from '../../shared/components/page-header/page-header';
import { StatusBadge } from '../../shared/components/status-badge/status-badge';
import { FileSizePipe } from '../../shared/pipes/file-size.pipe';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { StrategyHintPipe } from '../../shared/pipes/strategy-hint.pipe';

@Component({
  selector: 'app-documents-page',
  imports: [
    DatePipe,
    DecimalPipe,
    FormsModule,
    ConfirmDialog,
    EmptyState,
    ErrorState,
    LoadingIndicator,
    PageHeader,
    StatusBadge,
    FileSizePipe,
    RelativeTimePipe,
    StrategyHintPipe,
  ],
  templateUrl: './documents-page.html',
  styleUrl: './documents-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DocumentsPage {
  private readonly api = inject(DocumentApiService);
  private readonly notifications = inject(NotificationService);
  protected readonly serverConfig = inject(ServerConfigService);

  protected readonly documents = signal<DocumentInfo[]>([]);
  protected readonly index = signal<IndexStatus | null>(null);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<ApiError | null>(null);

  protected readonly uploading = signal(false);
  protected readonly uploadProgress = signal(0);
  protected readonly rebuilding = signal(false);
  protected readonly strategy = signal<ChunkStrategy>('heading');
  protected readonly pendingDelete = signal<DocumentInfo | null>(null);
  protected readonly deleting = signal(false);
  protected readonly dragging = signal(false);

  protected readonly pendingCount = computed(() => this.documents().filter((doc) => doc.status !== 'indexed').length);
  protected readonly needsRebuild = computed(() => this.pendingCount() > 0 || !this.index()?.ready);
  protected readonly acceptedExtensions = computed(() =>
    (this.serverConfig.settings()?.supported_extensions ?? ['.pdf', '.md', '.markdown', '.txt']).join(','),
  );
  protected readonly maxUploadMb = computed(() => this.serverConfig.settings()?.max_upload_mb ?? 20);

  constructor() {
    this.serverConfig.load();
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set(null);
    try {
      const response = await firstValueFrom(this.api.list());
      this.documents.set(response.documents);
      this.index.set(response.index);
      if (response.index.strategy) {
        this.strategy.set(response.index.strategy);
      }
    } catch (error) {
      this.loadError.set(error as ApiError);
    } finally {
      this.loading.set(false);
    }
  }

  protected onFileInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = input.files ? Array.from(input.files) : [];
    input.value = '';
    void this.uploadFiles(files);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    const files = event.dataTransfer?.files ? Array.from(event.dataTransfer.files) : [];
    void this.uploadFiles(files);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }

  async uploadFiles(files: File[]): Promise<void> {
    if (!files.length || this.uploading()) {
      return;
    }

    const accepted = this.acceptedExtensions().split(',');
    const limit = this.maxUploadMb() * 1024 * 1024;

    for (const file of files) {
      const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`;
      if (!accepted.includes(extension)) {
        this.notifications.error(`${file.name}: unsupported type. Allowed: ${accepted.join(', ')}`);
        continue;
      }
      if (file.size > limit) {
        this.notifications.error(`${file.name}: larger than the ${this.maxUploadMb()} MB limit.`);
        continue;
      }
      await this.uploadOne(file);
    }

    await this.load();
  }

  private uploadOne(file: File): Promise<void> {
    this.uploading.set(true);
    this.uploadProgress.set(0);

    return new Promise((resolve) => {
      this.api.upload(file).subscribe({
        next: (event) => {
          if (event.type === HttpEventType.UploadProgress && event.total) {
            this.uploadProgress.set(Math.round((event.loaded / event.total) * 100));
          } else if (event.type === HttpEventType.Response && event.body) {
            this.notifications.success(event.body.message);
          }
        },
        error: (error: ApiError) => {
          this.notifications.error(`${file.name}: ${error.message}`);
          this.uploading.set(false);
          resolve();
        },
        complete: () => {
          this.uploading.set(false);
          resolve();
        },
      });
    });
  }

  async rebuild(): Promise<void> {
    if (this.rebuilding()) {
      return;
    }
    this.rebuilding.set(true);
    try {
      const result = await firstValueFrom(this.api.rebuild(this.strategy()));
      this.notifications.success(
        `Index rebuilt: ${result.documents} documents, ${result.chunks.toLocaleString()} chunks (${this.serverConfig.strategyLabel(result.strategy).toLowerCase()}).`,
      );
      await this.load();
    } catch (error) {
      this.notifications.error((error as ApiError).message);
    } finally {
      this.rebuilding.set(false);
    }
  }

  protected askDelete(document: DocumentInfo): void {
    this.pendingDelete.set(document);
  }

  async confirmDelete(): Promise<void> {
    const document = this.pendingDelete();
    if (!document) {
      return;
    }
    this.deleting.set(true);
    try {
      const result = await firstValueFrom(this.api.delete(document.name));
      this.notifications.success(result.message);
      this.pendingDelete.set(null);
      await this.load();
    } catch (error) {
      this.notifications.error((error as ApiError).message);
    } finally {
      this.deleting.set(false);
    }
  }
}
