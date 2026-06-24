"""
SAM v2.0 - Image Generation (Enhanced)
Modern image generation with quality presets, prompt enhancement, and multiple providers.
"""

import logging
import requests
import base64
import urllib.parse
from typing import Optional, Dict, List
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class ImageGenerator:
    """
    Enhanced image generator with modern standards:
    - Higher resolution defaults (1024x1024)
    - Prompt enhancement for better results
    - Quality presets (draft, normal, high, ultra)
    - Multiple provider fallbacks
    - Style presets (photorealistic, anime, art, etc.)
    """
    
    # Output directory
    OUTPUT_DIR = Path.home() / "Pictures" / "sam_generated"
    
    # Quality presets
    QUALITY_PRESETS = {
        'draft': {'steps': 15, 'cfg': 5.0, 'width': 512, 'height': 512},
        'normal': {'steps': 25, 'cfg': 7.0, 'width': 768, 'height': 768},
        'high': {'steps': 35, 'cfg': 7.5, 'width': 1024, 'height': 1024},
        'ultra': {'steps': 50, 'cfg': 8.0, 'width': 1024, 'height': 1024},
    }
    
    # Style presets with prompt enhancers
    STYLE_PRESETS = {
        'photorealistic': {
            'suffix': ', photorealistic, 8k uhd, high detail, professional photography, sharp focus, natural lighting',
            'negative': 'cartoon, anime, drawing, painting, illustration, cgi, 3d render, low quality, blurry'
        },
        'anime': {
            'suffix': ', anime style, studio ghibli, detailed anime art, vibrant colors, clean lines',
            'negative': 'photorealistic, photograph, 3d, western cartoon, low quality, blurry'
        },
        'art': {
            'suffix': ', digital art, artstation, trending, highly detailed, concept art, beautiful composition',
            'negative': 'photograph, photo, realistic, low quality, amateur'
        },
        'cinematic': {
            'suffix': ', cinematic lighting, movie scene, dramatic, volumetric lighting, film grain, anamorphic',
            'negative': 'flat lighting, amateur, low budget, low quality'
        },
        'minimal': {
            'suffix': ', minimalist, clean, simple, elegant design',
            'negative': 'complex, busy, cluttered, noisy'
        },
        'none': {
            'suffix': '',
            'negative': 'ugly, blurry, low quality, distorted, deformed, bad anatomy'
        }
    }
    
    # Base negative prompt for all generations
    BASE_NEGATIVE = "ugly, deformed, noisy, blurry, distorted, grainy, bad anatomy, bad proportions, watermark, signature, text"
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # SD WebUI settings
        self.sd_url = self.config.get('sd_url', 'http://localhost:7860')
        self.sd_enabled = False
        
        # ComfyUI settings (alternative)
        self.comfy_url = self.config.get('comfy_url', 'http://localhost:8188')
        self.comfy_enabled = False
        
        # Ensure output directory exists
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Check available backends
        self._check_backends()
        
        logger.info(f"[Sam] ImageGenerator initialized (SD: {self.sd_enabled})")
    
    def _check_backends(self):
        """Check available generation backends"""
        # Check Automatic1111 SD WebUI
        try:
            response = requests.get(f"{self.sd_url}/sdapi/v1/options", timeout=2)
            if response.status_code == 200:
                self.sd_enabled = True
                logger.info("[Sam] Stable Diffusion WebUI detected")
        except:
            pass
        
        # Check ComfyUI
        try:
            response = requests.get(f"{self.comfy_url}/system_stats", timeout=2)
            if response.status_code == 200:
                self.comfy_enabled = True
                logger.info("[Sam] ComfyUI detected")
        except:
            pass
    
    def enhance_prompt(self, prompt: str, style: str = 'none') -> tuple:
        """
        Enhance prompt with style modifiers and quality boosters.
        
        Returns:
            Tuple of (enhanced_prompt, negative_prompt)
        """
        style_config = self.STYLE_PRESETS.get(style, self.STYLE_PRESETS['none'])
        
        # Add quality boosters
        enhanced = prompt.strip()
        
        # Add style suffix
        if style_config['suffix']:
            enhanced += style_config['suffix']
        
        # Combine negative prompts
        negative = self.BASE_NEGATIVE
        if style_config['negative']:
            negative = style_config['negative'] + ", " + self.BASE_NEGATIVE
        
        return enhanced, negative
    
    def generate_sd(
        self,
        prompt: str,
        negative_prompt: str = None,
        quality: str = 'high',
        style: str = 'none',
        width: int = None,
        height: int = None,
        **kwargs
    ) -> Optional[str]:
        """
        Generate image using local Stable Diffusion with enhanced settings.
        """
        if not self.sd_enabled:
            return None
        
        # Get quality preset
        preset = self.QUALITY_PRESETS.get(quality, self.QUALITY_PRESETS['high'])
        
        # Enhance prompt
        enhanced_prompt, auto_negative = self.enhance_prompt(prompt, style)
        
        # Use provided or preset values
        final_width = width or preset['width']
        final_height = height or preset['height']
        final_negative = negative_prompt or auto_negative
        
        try:
            payload = {
                "prompt": enhanced_prompt,
                "negative_prompt": final_negative,
                "width": final_width,
                "height": final_height,
                "steps": preset['steps'],
                "cfg_scale": preset['cfg'],
                "sampler_name": "DPM++ 2M Karras",  # Modern sampler
                "scheduler": "karras",
                "restore_faces": True,
                "enable_hr": quality in ['high', 'ultra'],  # Hires fix for quality
                "hr_scale": 1.5 if quality == 'ultra' else 1.2,
                "hr_upscaler": "Latent",
                "denoising_strength": 0.5
            }
            
            # Remove hires options if not enabled
            if quality not in ['high', 'ultra']:
                payload.pop('enable_hr', None)
                payload.pop('hr_scale', None)
                payload.pop('hr_upscaler', None)
                payload.pop('denoising_strength', None)
            
            response = requests.post(
                f"{self.sd_url}/sdapi/v1/txt2img",
                json=payload,
                timeout=180
            )
            
            if response.status_code == 200:
                data = response.json()
                images = data.get('images', [])
                
                if images:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"sam_sd_{timestamp}.png"
                    filepath = self.OUTPUT_DIR / filename
                    
                    image_data = base64.b64decode(images[0])
                    with open(filepath, 'wb') as f:
                        f.write(image_data)
                    
                    logger.info(f"[Sam] SD image generated: {filepath}")
                    return str(filepath)
            
            return None
            
        except Exception as e:
            logger.error(f"[Sam] SD generation error: {e}")
            return None
    
    def generate_pollinations(
        self,
        prompt: str,
        style: str = 'none',
        width: int = 1024,
        height: int = 1024,
        model: str = 'flux'  # Use FLUX model for best quality
    ) -> Optional[str]:
        """
        Generate image using Pollinations.ai with modern models.
        
        Models available:
        - flux: Best quality, slower
        - turbo: Faster, good quality
        """
        try:
            # Enhance prompt
            enhanced_prompt, _ = self.enhance_prompt(prompt, style)
            encoded_prompt = urllib.parse.quote(enhanced_prompt)
            
            # Build URL with modern parameters
            url = (
                f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                f"?width={width}"
                f"&height={height}"
                f"&model={model}"
                f"&nologo=true"
                f"&enhance=true"
                f"&seed={int(datetime.now().timestamp())}"
            )
            
            print(f"[Pollinations] Generando con {model.upper()}...")
            
            response = requests.get(url, timeout=90)
            
            if response.status_code == 200:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"sam_flux_{timestamp}.png"
                filepath = self.OUTPUT_DIR / filename
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"[Sam] Pollinations image generated: {filepath}")
                return str(filepath)
            
            return None
            
        except Exception as e:
            logger.error(f"[Sam] Pollinations error: {e}")
            return None
    
    def generate_flux_local(
        self,
        prompt: str,
        width: int = 512,
        height: int = 512,
        num_steps: int = 4,
        guidance_scale: float = 0.0
    ) -> Optional[str]:
        """
        Generate image using local SDXL-Turbo model.
        
        SDXL-Turbo is fast and doesn't require authentication.
        Uses ~6GB RAM on CPU, ~4GB VRAM on GPU.
        
        First run will download the model (~5GB).
        """
        try:
            import torch
            from diffusers import AutoPipelineForText2Image
            
            print("[Local] Cargando SDXL-Turbo (primera vez descarga ~5GB)...")
            
            # Use SDXL-Turbo (no auth required, fast)
            pipe = AutoPipelineForText2Image.from_pretrained(
                "stabilityai/sdxl-turbo",
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                variant="fp16" if torch.cuda.is_available() else None
            )
            
            # Move to appropriate device
            if torch.cuda.is_available():
                pipe = pipe.to("cuda")
                print("[Local] Usando GPU...")
            else:
                print("[Local] Usando CPU (más lento, ~2-3 min)...")
            
            print(f"[Local] Generando: '{prompt[:50]}...'")
            
            # Generate (SDXL-Turbo uses 1-4 steps, no CFG needed)
            image = pipe(
                prompt=prompt,
                num_inference_steps=4,
                guidance_scale=0.0,
                width=width,
                height=height
            ).images[0]
            
            # Save
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"sam_local_{timestamp}.png"
            filepath = self.OUTPUT_DIR / filename
            image.save(filepath)
            
            # Cleanup to free memory
            del pipe
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            logger.info(f"[Sam] Local image generated: {filepath}")
            return str(filepath)
            
        except ImportError as e:
            logger.error(f"[Sam] Local gen requires: pip install diffusers torch")
            return None
        except Exception as e:
            logger.error(f"[Sam] Local gen error: {e}")
            print(f"[Local] Error: {e}")
            return None
    
    def generate_placeholder(self, prompt: str, width: int = 512, height: int = 512) -> str:
        """Generate placeholder when no backend available"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            
            # Dark modern placeholder
            img = Image.new('RGB', (width, height), color=(18, 18, 18))
            draw = ImageDraw.Draw(img)
            
            # Gradient-like overlay
            for i in range(height):
                alpha = int(20 + (i / height) * 30)
                draw.line([(0, i), (width, i)], fill=(alpha, alpha, alpha + 10))
            
            # Modern border
            draw.rectangle([15, 15, width-15, height-15], outline=(99, 102, 241), width=2)
            
            # Load font - try multiple paths
            font = None
            font_paths = [
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            ]
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, 18)
                    font_small = ImageFont.truetype(fp, 14)
                    break
                except:
                    continue
            
            if not font:
                font = ImageFont.load_default()
                font_small = font
            
            # Text (ASCII safe, no emojis)
            text = f"[IMG] {prompt[:30]}..." if len(prompt) > 30 else f"[IMG] {prompt}"
            bbox = draw.textbbox((0, 0), text, font=font)
            x = (width - (bbox[2] - bbox[0])) // 2
            draw.text((x, height//2 - 20), text, fill=(255, 255, 255), font=font)
            draw.text((x, height//2 + 10), "(Sin backend de generación)", fill=(156, 163, 175), font=font_small)
            
            # Save
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = self.OUTPUT_DIR / f"sam_placeholder_{timestamp}.png"
            img.save(filepath)
            
            return str(filepath)
            
        except ImportError:
            return None
    
    def generate(
        self,
        prompt: str,
        quality: str = 'high',
        style: str = 'photorealistic',
        **kwargs
    ) -> Dict:
        """
        Main generation method with intelligent fallbacks.
        
        Args:
            prompt: Image description
            quality: draft/normal/high/ultra
            style: photorealistic/anime/art/cinematic/minimal/none
            **kwargs: Additional parameters
        
        Returns:
            Dict with success status, path, and metadata
        """
        # Try local SD first (best quality control)
        if self.sd_enabled:
            path = self.generate_sd(prompt, quality=quality, style=style, **kwargs)
            if path:
                return {
                    'success': True,
                    'path': path,
                    'method': 'stable_diffusion',
                    'quality': quality,
                    'style': style,
                    'prompt': prompt
                }
        
        # Try Pollinations with FLUX (high quality, free)
        path = self.generate_pollinations(prompt, style=style, model='flux')
        if path:
            return {
                'success': True,
                'path': path,
                'method': 'pollinations_flux',
                'quality': 'high',
                'style': style,
                'prompt': prompt
            }
        
        # Try Pollinations turbo (faster fallback)
        path = self.generate_pollinations(prompt, style=style, model='turbo')
        if path:
            return {
                'success': True,
                'path': path,
                'method': 'pollinations_turbo',
                'quality': 'normal',
                'style': style,
                'prompt': prompt
            }
        
        # Placeholder as last resort
        path = self.generate_placeholder(prompt)
        if path:
            return {
                'success': True,
                'path': path,
                'method': 'placeholder',
                'prompt': prompt,
                'note': 'No backend available'
            }
        
        return {'success': False, 'error': 'No generation method available'}
    
    def get_status(self) -> Dict:
        """Get generator status"""
        return {
            'sd_enabled': self.sd_enabled,
            'sd_url': self.sd_url,
            'comfy_enabled': self.comfy_enabled,
            'pollinations': True,
            'output_dir': str(self.OUTPUT_DIR),
            'quality_presets': list(self.QUALITY_PRESETS.keys()),
            'style_presets': list(self.STYLE_PRESETS.keys())
        }
    
    def list_styles(self) -> List[str]:
        """List available style presets"""
        return list(self.STYLE_PRESETS.keys())
